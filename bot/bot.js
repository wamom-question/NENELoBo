import dotenv from 'dotenv';
dotenv.config();  // .envファイルを読み込む

import { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder, EmbedBuilder, GuildScheduledEventEntityType, GuildScheduledEventPrivacyLevel } from 'discord.js';
import fetch from 'node-fetch';
import fs from 'fs';
import { setupBumpNoticeHandler, handleNextBumpCommand, setupNextBumpOnStartup } from './BumpNotice.js';
import { performSimpleGachaDraw, performGacha100, performGacha10, calculateCombinationProbability } from './gacha.js';
import { Blob } from 'buffer';
import FormData from 'form-data';

// 環境変数から設定を読み込む
const token = process.env.DISCORD_TOKEN;
const clientId = process.env.CLIENT_ID;
const channelId = process.env.ANNOUNCEMENT_CHANNEL_ID;  // お知らせを送るチャンネルID
const guildId = process.env.GUILD_ID; // テスト用のギルドID
const ANNOUNCEMENT_API = process.env.ANNOUNCEMENT_API || 'http://python_announce_fetcher:5000/announcements'; // PythonのAPIエンドポイント

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
    .setDescription('BotのPingを返します。')
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
    if (text && text.trim() !== "新しいお知らせはありません。") {
      return text;
    }
    return null;
  } catch (error) {
    console.error(`API 接続エラー: ${error.message}`);
    return null;
  }
}

async function handleAnnouncementText(text) {
  if (!text) return;
  const channel = client.channels.cache.get(channelId);
  if (channel) {
    channel.send(text + "\n\n<@&1307026514071523341>");
  } else {
    console.error('チャンネルが見つかりません。');
  }

  // 🔍「プロセカ放送局#◯◯」に一致した場合、イベント作成
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

    if (channel) {
      channel.send(`📢 Discordイベントを作成しました！\n${event.url}`);
    }

    console.log(`✅ Discordイベント「プロセカ放送局#${number}」を作成しました。`);
  }
}

// コマンド実行時の処理
client.on('interactionCreate', async interaction => {
  console.log('💬 interactionCreate イベントが発生:', interaction.commandName);
  if (!interaction.isChatInputCommand()) return;

  if (interaction.commandName === 'nenelobo') {
    const ping = client.ws.ping;
    await interaction.reply(`BotのPingは${ping}msです！`);
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
  } else if (interaction.commandName === 'nextbump') {
    await handleNextBumpCommand(interaction, client);
  }
});

// メンション＋画像添付メッセージを検知し、画像をPython OCR APIに送信
client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (message.mentions.has(client.user) && message.attachments.size > 0) {
    const isDebug = message.content.toLowerCase().includes('debug');
    for (const attachment of message.attachments.values()) {
      if (attachment.contentType && attachment.contentType.startsWith('image')) {
        try {
          // node-fetch v3以降推奨: response.arrayBuffer() でbuffer取得
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
            let reply = result.results.map(player => {
              if (player.error) {
                return `Player_${player.player}: 認識失敗 (${player.error})`;
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
          } else {
            await message.reply('画像から有効なスコアが認識できませんでした。');
          }

          // デバッグ用画像・サマリーがAPIレスポンスに含まれていれば送信
          if (isDebug && result.debug_image_base64) {
            // Base64データをBufferに変換してDiscordに送信
            const imageBuffer = Buffer.from(result.debug_image_base64, 'base64');
            await message.channel.send({ content: '（デバッグ用）読み取り部分にラベルをつけた画像です:', files: [{ attachment: imageBuffer, name: 'labeled_result.png' }] });
          }
          if (isDebug && result.debug_summary) {
            await message.channel.send(`${message.author.toString()} の認識結果:\n${result.debug_summary}`);
          }
          // 各プレイヤーのデバッグ画像・パラメータも送信
          if (isDebug && result.results && Array.isArray(result.results)) {
            for (const player of result.results) {
              if (player.crop_image_base64) {
                const cropBuf = Buffer.from(player.crop_image_base64, 'base64');
                await message.channel.send({ content: `Player_${player.player} 切り抜き画像`, files: [{ attachment: cropBuf, name: `player${player.player}_crop.png` }] });
              }
              if (player.preprocessed_image_base64) {
                const preBuf = Buffer.from(player.preprocessed_image_base64, 'base64');
                await message.channel.send({ content: `Player_${player.player} 前処理後画像`, files: [{ attachment: preBuf, name: `player${player.player}_preprocessed.png` }] });
              }
              if (player.preprocess_params) {
                await message.channel.send({ content: `Player_${player.player} 前処理パラメータ: \n${JSON.stringify(player.preprocess_params, null, 2)}` });
              }
            }
          }
        } catch (err) {
          await message.reply('OCR API通信または画像処理でエラーが発生しました。');
          console.error(err);
        }
      }
    }
  }
});

// Botトークンでログイン
client.login(token);