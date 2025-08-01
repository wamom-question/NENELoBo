import dotenv from 'dotenv';
dotenv.config();  // .envファイルを読み込む

import { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder, EmbedBuilder, GuildScheduledEventEntityType, GuildScheduledEventPrivacyLevel } from 'discord.js';
import fetch from 'node-fetch';
import { promises as fs } from 'fs';
import { setupBumpNoticeHandler, handleNextBumpCommand, setupNextBumpOnStartup } from './BumpNotice.js';
import { performSimpleGachaDraw, performGacha100, performGacha10, calculateCombinationProbability } from './gacha.js';
import FormData from 'form-data';

// 環境変数から設定を読み込む
const token = process.env.DISCORD_TOKEN;
const clientId = process.env.CLIENT_ID;
const channelId = process.env.ANNOUNCEMENT_CHANNEL_ID;  // お知らせを送るチャンネルID
const guildId = process.env.GUILD_ID; // テスト用のギルドID
const ANNOUNCEMENT_API = process.env.ANNOUNCEMENT_API || 'http://python_announce_fetcher:5000/announcements'; // PythonのAPIエンドポイント
const ocrAlwaysChannelIds = process.env.OCR_ALWAYS_CHANNEL_ID
  ? process.env.OCR_ALWAYS_CHANNEL_ID.split(',').map(id => id.trim())
  : [];
const priorityQueue = [];
const normalQueue = [];

// OCR APIエンドポイント
const OCR_API_URL = 'http://python_result_calc:5000/ocr';

// クライアントの作成
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent
  ]
});

// スラッシュコマンドの定義
const commands = [
  new SlashCommandBuilder()
    .setName('nenelobo')
    .setDescription('Botの情報を返します。')
    .toJSON(),
  new SlashCommandBuilder()
    .setName('gacha')
    .setDescription('ガチャを引きます！')
    .addIntegerOption(option =>
      option.setName('pulls')
        .setDescription('引く回数（1, 10 または 100）')
        .addChoices(
          { name: '1回', value: 1 },
          { name: '10回', value: 10 },
          { name: '100回', value: 100 }
        )
        .setRequired(true)
    )
    .toJSON(),
  // メッセージコンテキストメニューコマンドを追加
  {
    name: 'リアクション',
    type: 3 // 3 = MESSAGE
  }
];

// REST APIクライアントを作成してコマンド登録を実施
const rest = new REST({ version: '10' }).setToken(token);

(async () => {
  try {
    console.log('Started refreshing application (/) commands.');
    if (!clientId || !guildId) {
      console.error('CLIENT_ID または GUILD_ID が設定されていません。');
      return;
    }
    await rest.put(
      Routes.applicationGuildCommands(clientId, guildId),
      { body: commands }
    );
    console.log('Successfully reloaded application (/) commands.');
  } catch (error) {
    console.error(error);
  }
})();

// Botが起動したらログ出力
client.once('ready', async () => {
  console.log('Bot is online!');
  // お知らせ送信を毎分スケジューリング
  const now = new Date();
  const delay = ((60 - now.getSeconds() + 1) % 60) * 1000;
  setTimeout(() => {
    setInterval(async () => {
      const now = new Date();
      const minutes = now.getMinutes();
      const shouldFetch =
        minutes === 0 ||
        minutes === 1 ||
        minutes === 30 ||
        minutes === 31 ||
        minutes % 5 === 0;

      if (shouldFetch) {
        const text = await fetchAnnouncementText();
        if (text) {
          latestAnnouncementText = text;
        }
      }

      if (latestAnnouncementText) {
        await handleAnnouncementText(latestAnnouncementText);
        latestAnnouncementText = null;
      }
    }, 60 * 1000);
  }, delay);
  console.log('📦 BumpNotice handler を登録します');
  setupBumpNoticeHandler(client);

  // Bot起動時にnextbump通知の予約
  setupNextBumpOnStartup(client);
});

let latestAnnouncementText = null;

async function fetchAnnouncementText() {
  try {
    const response = await fetch(ANNOUNCEMENT_API);
    const text = await response.text();

    // 無意味な場合は null を返す
    if (!text || text.trim() === "新しいお知らせはありません。") {
      return null;
    }

    return text;
  } catch (error) {
    console.error(`API 接続エラー: ${error.message}`);
    return null;
  }
}

async function handleAnnouncementText(text) {
  if (!text) return; // null や空文字なら即終了

  const channel = client.channels.cache.get(channelId);
  if (!channel) {
    console.error('チャンネルが見つかりません。');
    return;
  }

  // 通常メッセージ送信
  await channel.send(text + "\n\n<@&1307026514071523341>");

  // 放送局のメッセージにマッチしたら Discordイベント作成
  const match = text.match(/(\d{1,2})月(\d{1,2})日(\d{1,2})時(\d{1,2})分より「プロセカ放送局#(\d+)」を生配信/);
  if (match) {
    const [, monthStr, dayStr, hourStr, minuteStr, numberStr] = match;
    const month = Number(monthStr);
    const day = Number(dayStr);
    const hour = Number(hourStr);
    const minute = Number(minuteStr);
    const number = Number(numberStr);

    const now = new Date();
    const year = (now.getMonth() + 1 > month) ? now.getFullYear() + 1 : now.getFullYear();

    const jstStart = new Date(year, month - 1, day, hour, minute);
    const utcStart = new Date(jstStart.getTime() - 9 * 60 * 60 * 1000);
    const utcEnd = new Date(utcStart.getTime() + 2 * 60 * 60 * 1000);

    if (guildId && client.guilds.cache.has(guildId)) {
      const guild = await client.guilds.fetch(guildId);
      const event = await guild.scheduledEvents.create({
        name: `プロセカ放送局#${number}`,
        scheduledStartTime: utcStart,
        scheduledEndTime: utcEnd,
        privacyLevel: GuildScheduledEventPrivacyLevel.GuildOnly,
        entityType: GuildScheduledEventEntityType.Voice,
        channel: '1248602145133953046',
        description: '「プロセカ放送局」の生配信イベントです。',
      });

      await channel.send(`📢 Discordイベントを作成しました！\n${event.url}`);
      console.log(`✅ Discordイベント「プロセカ放送局#${number}」を作成しました。`);
    }
  }
}

// コマンド実行時の処理
client.on('interactionCreate', async interaction => {
  console.log('💬 interactionCreate イベントが発生:', interaction.commandName);
  if (interaction.isChatInputCommand()) {
  if (interaction.commandName === 'nenelobo') {
    const ping = client.ws.ping;

    // 外部テキストファイルを読み込む
    let rawText;
    try {
      rawText = await fs.readFile('/app/data/ping_message.txt', 'utf-8');
    } catch (err) {
      console.error('ping_message.txt の読み込みに失敗:', err);
      rawText = 'BotのPingは${ping}msです！'; // fallback
    }

    // テキスト内の ${ping} を置換
    const replacedText = rawText.replace(/\$\{ping\}/g, `${ping}`);

    // Embedメッセージとして送信
    const embed = new EmbedBuilder()
      .setColor('Blue')
      .setTitle('📶 Ping 結果')
      .setDescription(replacedText)
      .setTimestamp();

    await interaction.reply({ embeds: [embed] });
  } else if (interaction.commandName === 'gacha') {
      const pulls = interaction.options.getInteger('pulls');

      if (pulls === 100) {
        // 100回引く処理
        const results = [];
        let star2 = 0, star3 = 0, star4Constant = 0, star4Pickup = 0;

        for (let j = 0; j < 10; j++) {
          const row = [];
          let star2Count = 0;

          // 1〜9回目
          for (let i = 0; i < 9; i++) {
            const rand = Math.random() * 100;
            if (rand < 88.5) { row.push(process.env.EMOJI_STAR2); star2++; star2Count++; }
            else if (rand < 97) { row.push(process.env.EMOJI_STAR3); star3++; }
            else if (rand < 98.8) { row.push(process.env.EMOJI_STAR4); star4Pickup++; }
            else { row.push(process.env.EMOJI_STAR4); star4Constant++; }
          }

          // 10回目
          const rand = Math.random() * 100;
          if (star2Count === 9) {
            if (rand < 97) { row.push(process.env.EMOJI_STAR3); star3++; }
            else if (rand < 98.8) { row.push(process.env.EMOJI_STAR4); star4Pickup++; }
            else { row.push(process.env.EMOJI_STAR4); star4Constant++; }
          } else {
            if (rand < 88.5) { row.push(process.env.EMOJI_STAR2); star2++; }
            else if (rand < 97) { row.push(process.env.EMOJI_STAR3); star3++; }
            else if (rand < 98.8) { row.push(process.env.EMOJI_STAR4); star4Pickup++; }
            else { row.push(process.env.EMOJI_STAR4); star4Constant++; }
          }

          results.push(row);
        }

        const thinkingEmbed = new EmbedBuilder()
          .setTitle('100回引いています...')
          .setColor('Grey')
          .setTimestamp();

        await interaction.reply({ embeds: [thinkingEmbed] });
        const embedMsg = await interaction.fetchReply();

        // 10回ずつephemeralメッセージで送信
        for (let i = 0; i < results.length; i++) {
          const chunk = results[i].join(' ');
          await interaction.followUp({
            content: chunk,
            ephemeral: true
          });
        }

        // 統計結果でembedを編集
        const resultEmbed = new EmbedBuilder()
          .setTitle('100回引きました。')
          .setDescription(`> 星2..............${star2}枚\n> 星3..............${star3}枚\n> 星4(恒常)...${star4Constant}枚\n> 星4(PU)......${star4Pickup}枚`)
          .setColor('Green')
          .setTimestamp();

        await embedMsg.edit({ embeds: [resultEmbed] });
      } else if (pulls === 10) {
        // 10回引く処理
        // performGacha10で詳細な内訳とラスト1枠の型を取得
        const {
          results,
          star2Count,
          star3Count,
          constantCount,
          pickupCount,
          lastDrawType
        } = performGacha10();

        const line1 = results.slice(0, 5).join(' ');
        const line2 = results.slice(5).join(' ');

        // 組み合わせ確率を計算
        const draws = [star2Count - (lastDrawType === 'star2' ? 1 : 0),
                       star3Count - (lastDrawType === 'star3' ? 1 : 0),
                       constantCount - (lastDrawType === 'constant' ? 1 : 0),
                       pickupCount - (lastDrawType === 'pickup' ? 1 : 0)];
        const prob = calculateCombinationProbability(draws, lastDrawType);
        const percent = (prob * 100).toFixed(4);

        const summary = [];
        if (constantCount > 0) summary.push(`恒常が${constantCount}枚出ました。`);
        if (pickupCount > 0) summary.push(`ピックアップが${pickupCount}枚出ました。`);
        summary.push(`🎲 この組み合わせが出る確率は約 ${percent}% です。`);

        await interaction.reply(`${line1}\n${line2}`);
        await interaction.followUp(summary.join('\n'));
      } else {
        // 1回引く処理
        const { results, newMemberCount, slipCount } = performSimpleGachaDraw(pulls);

        const line1 = results.slice(0, 5).join(' ');
        const line2 = results.slice(5).join(' ');
        const summary = [];
        if (slipCount > 0) summary.push(`恒常が${slipCount}枚出ました。`);
        if (newMemberCount > 0) summary.push(`ピックアップが${newMemberCount}枚出ました。`);

        await interaction.reply(`${line1}\n${line2}`);
        if (summary.length > 0) {
          await interaction.followUp(summary.join('\n'));
        }
      }
  }
}});

// メンション＋画像添付メッセージを検知し、画像をPython OCR APIに送信
client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (message.mentions.has(client.user) && message.attachments.size > 0) {
    const isDebug = message.content.toLowerCase().includes('debug');
    for (const attachment of message.attachments.values()) {
      if (attachment.contentType && attachment.contentType.startsWith('image')) {
        try {
          const response = await fetch(attachment.url);
          const arrayBuffer = await response.arrayBuffer();
          const buffer = Buffer.from(arrayBuffer);

          const form = new FormData();
          form.append('image', buffer, { filename: 'image.png', contentType: 'image/png' });
          form.append('debug', isDebug ? '1' : '0');

          const ocrRes = await fetch(OCR_API_URL, {
            method: 'POST',
            body: form,
            headers: form.getHeaders()
          });
          const result = await ocrRes.json();

          if (result && result.results && result.results.length > 0) {
            if (result.results.length >= 2) {
              // 2人以上なら表形式＋順位でまとめて返信
              const fields = ['perfect', 'great', 'good', 'bad', 'miss', 'score'];
              const labels = [
                'PERFECT(3)', 'GREAT(2)', 'GOOD(1)', 'BAD(0)', 'MISS(0)', 'score'
              ];
              const table = fields.map(() => []);
              result.results.forEach(player => {
                table[0].push(player.perfect);
                table[1].push(player.great);
                table[2].push(player.good);
                table[3].push(player.bad);
                table[4].push(player.miss);
                table[5].push(player.score);
              });

              let header = '              ' + table[0].map((_, i) => (i+1).toString().padEnd(4)).join(' ');
              let lines = [header];
              for (let i = 0; i < fields.length; i++) {
                let row = labels[i].padEnd(12) + ': ';
                row += table[i].map(v => String(v).padEnd(4)).join(' ');
                lines.push(row);
              }

              // スコアで順位付け
              const scores = result.results.map((p, i) => ({ idx: i + 1, score: p.score }));
              scores.sort((a, b) => b.score - a.score);
              const rankLines = scores.map((s, i) => {
                const rank = i + 1;
                const player = `Player_${s.idx}`;
                if (rank === 1) return `# 1位    ${player}`;
                if (rank === 2) return `## 2位    ${player}`;
                if (rank === 3) return `## 3位    ${player}`;
                return `${rank}位    ${player}`;
              });

              const reply = [
                '### 認識結果',
                '```',
                ...lines,
                '```',
                ...rankLines
              ].join('\n');
              await message.reply(reply);
            } else {
              // 1人だけなら従来通り
              let reply = result.results.map(player => {
                if (player.error) {
                  if (player.error.startsWith('数値変換に失敗')) {
                    return `Player_${player.player}: 認識失敗（数値変換エラー）`;
                  } else if (player.error === 'スコア認識に失敗') {
                    return `Player_${player.player}: 認識失敗（スコア認識エラー）`;
                  } else {
                    return `Player_${player.player}: 認識失敗 (${player.error})`;
                  }
                } else {
                  return [
                    `### Player_${player.player} 認識結果`,
                    '```',
                    `PERFECT(3)  : ${player.perfect}`,
                    `GREAT(2)    : ${player.great}`,
                    `GOOD(1)     : ${player.good}`,
                    `BAD(0)      : ${player.bad}`,
                    `MISS(0)     : ${player.miss}`,
                    '```',
                    '',
                    `## ランクマスコア  ${player.score}`
                  ].join('\n');
                }
              }).join('\n\n');
              await message.reply(reply);
            }
          } else {
            await message.react('<:ocr_error_api:1389800393332101311>');
            console.error('OCR APIレスポンスにresultsが無い、または空配列です:', result);
          }

          // デバッグ用画像・サマリーがAPIレスポンスに含まれていれば送信
          if (isDebug && result.debug_image_base64) {
            // Base64データをBufferに変換してDiscordに送信
            const imageBuffer = Buffer.from(result.debug_image_base64, 'base64');
            await message.channel.send({ content: '（デバッグ用）読み取り部分にラベルをつけた画像です:', files: [{ attachment: imageBuffer, name: 'labeled_result.png' }] });
          }
          // 各プレイヤーのデバッグ画像・パラメータも送信
          if (isDebug && result.results && Array.isArray(result.results)) {
            for (const player of result.results) {
              if (player.crop_image_base64) {
                const cropBuf = Buffer.from(player.crop_image_base64, 'base64');
                await message.channel.send({ content: `Player_${player.player} 切り抜き画像`, files: [{ attachment: cropBuf, name: `player${player.player}_crop.png` }] });
              }
              // Prefer simple_preprocess_image_base64 if present, fall back to preprocessed_image_base64
              if (player.simple_preprocess_image_base64 || player.preprocessed_image_base64) {
                const preBuf = Buffer.from(
                  player.simple_preprocess_image_base64 || player.preprocessed_image_base64,
                  'base64'
                );
                const preLabel = player.simple_preprocess_image_base64 ? '簡易前処理画像' : '前処理後画像';
                await message.channel.send({
                  content: `Player_${player.player} ${preLabel}`,
                  files: [{ attachment: preBuf, name: `player${player.player}_preprocessed.png` }]
                });
              }
              if (player.preprocess_params) {
                await message.channel.send({ content: `Player_${player.player} 前処理パラメータ: \n${JSON.stringify(player.preprocess_params, null, 2)}` });
              }
            }
          }
        } catch (err) {
          await message.reply('OCR処理中にエラーが発生しました。管理者にご連絡ください。');
          console.error(err);
        }
      }
    }
  }
});

// ocrAlwaysChannelId で画像付きメッセージが送信された場合にOCR APIへ送信
client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (ocrAlwaysChannelIds.includes(message.channel.id) && message.attachments.size > 0) {
    const imageAttachments = [...message.attachments.values()].filter(att => att.contentType && att.contentType.startsWith('image'));
    const isMultipleImages = imageAttachments.length >= 2;
        if (isMultipleImages) {
      const results = [];

      for (const attachment of imageAttachments) {
        try {
          const response = await fetch(attachment.url);
          const arrayBuffer = await response.arrayBuffer();
          const buffer = Buffer.from(arrayBuffer);

          const form = new FormData();
          form.append('image', buffer, { filename: 'image.png', contentType: 'image/png' });

          const ocrRes = await fetch(OCR_API_URL, {
            method: 'POST',
            body: form,
            headers: form.getHeaders()
          });

          const result = await ocrRes.json();
          results.push(result);
        } catch (err) {
          results.push({ error: 'API_ERROR' });
        }
      }

      for (const result of results) {
        if (result && result.results && result.results.length === 1) {
          const player = result.results[0];
          if (player.error) {
            if (player.error.startsWith('数値変換に失敗')) {
              await message.channel.send('<:ocr_error_convert:1389568868493561967>');
            } else if (player.error === 'スコア認識に失敗') {
              await message.channel.send('<:ocr_error_score:1389573918825775145>');
            } else {
              await message.channel.send('<:ocr_error:1389568660401684500>');
            }
          } else {
            let reply = `-# 認識結果 ${player.perfect} - ${player.great} - ${player.good} - ${player.bad} - ${player.miss}`;
            const replyMsg = await message.reply(reply);
            const scoreStr = String(player.score);
            await replyMsg.react('<:ocr_score:1389569033874968576>');
            await new Promise(res => setTimeout(res, 500));
            for (let i = 0; i < scoreStr.length; i++) {
              const digit = scoreStr[i];
              const pos = i + 1;
              const emojiId = process.env[`EMOJI_${digit}_${pos}`];
              if (emojiId) {
                await replyMsg.react(emojiId);
                await new Promise(res => setTimeout(res, 500));
              }
            }
          }
        } else {
          await message.channel.send('<:ocr_error_api:1389800393332101311>');
        }
      }
      return;
    }
    for (const attachment of imageAttachments) {
        try {
          const response = await fetch(attachment.url);
          const arrayBuffer = await response.arrayBuffer();
          const buffer = Buffer.from(arrayBuffer);
          const isDebug = false; // or true
          const form = new FormData();
          form.append('image', buffer, { filename: 'image.png', contentType: 'image/png' });
          form.append('debug', isDebug ? '1' : '0');

          const ocrRes = await fetch(OCR_API_URL, {
            method: 'POST',
            body: form,
            headers: form.getHeaders()
          });
          const result = await ocrRes.json();

          if (result && result.results && result.results.length > 0) {
            if (result.results.length >= 2) {
              // 2人以上ならメンションしてもう一度送るようにリアクション
              await message.react('<:ocr_error_2player:1389581609883406336>');
              await new Promise(res => setTimeout(res, 500));
              await message.react('<:ocr_error_info_mention:1389581588995768472>');
            } else {
              // 1人だけならスコアを桁ごとに分解してカスタム絵文字でリアクション（0埋めせず実際の桁数のみ）
              const player = result.results[0];
              if (player.error) {
                if (player.error.startsWith('数値変換に失敗')) {
                  await message.react('<:ocr_error_convert:1389568868493561967>');
                } else if (player.error === 'スコア認識に失敗') {
                  await message.react('<:ocr_error_score:1389573918825775145>');
                } else {
                  // その他のエラー
                  await message.react('<:ocr_error:1389568660401684500>');
                }
              } else {
                // スコアを左から右へ桁ごとに分解し、各桁・数字に対応するカスタム絵文字IDでリアクション
                const scoreStr = String(player.score);
                  await message.react('<:ocr_score:1389569033874968576>');
                  await new Promise(res => setTimeout(res, 500));
                for (let i = 0; i < scoreStr.length; i++) {
                  const digit = scoreStr[i];
                  const pos = i + 1; // 1始まり
                  const emojiId = process.env[`EMOJI_${digit}_${pos}`];
                  if (emojiId) {
                    await message.react(emojiId);
                    await new Promise(res => setTimeout(res, 500));
                  }
                }
              }
              // replyは従来通り
              let reply = [
                `-# 認識結果 ${player.perfect} - ${player.great} - ${player.good} - ${player.bad} - ${player.miss}`,
              ].join('\n');
              await message.reply(reply);
            }
          } else {
            await message.react('<:ocr_error_api:1389800393332101311>');
            console.error('OCR APIレスポンスにresultsが無い、または空配列です:', result);
          }
        } catch (err) {
          await message.reply('OCRが起動していない可能性があります。しばらくしてから再度お試しください。');
          console.error(err);
        }
      }
    }
  }
);

// Botトークンでログイン
client.login(token);