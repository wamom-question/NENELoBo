import dotenv from 'dotenv';
dotenv.config();  // .envファイルを読み込む

const eventChannelIds = process.env.EVENT_CHANNEL_ID
  ? process.env.EVENT_CHANNEL_ID.split(',').map(id => id.trim())
  : [];

import { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder, EmbedBuilder, GuildScheduledEventEntityType, GuildScheduledEventPrivacyLevel,PermissionsBitField } from 'discord.js';
import fetch from 'node-fetch';
import { promises as fs } from 'fs';
import { setupBumpNoticeHandler, handleNextBumpCommand, setupNextBumpOnStartup } from './BumpNotice.js';
import { performSimpleGachaDraw, performGacha100, performGacha10, calculateCombinationProbability } from './gacha.js';
import FormData from 'form-data';

// 環境変数から設定を読み込む
const token = process.env.DISCORD_TOKEN;
const clientId = process.env.CLIENT_ID;
// 複数のチャンネルIDとサーバーIDを配列として取得
const channelIds = process.env.ANNOUNCEMENT_CHANNEL_ID
  ? process.env.ANNOUNCEMENT_CHANNEL_ID.split(',').map(id => id.trim())
  : [];
const guildIds = process.env.GUILD_ID
  ? process.env.GUILD_ID.split(',').map(id => id.trim())
  : [];
const ANNOUNCEMENT_API = process.env.ANNOUNCEMENT_API || 'http://announce-fetcher:5000/announcements'; // PythonのAPIエンドポイント
const ocrAlwaysChannelIds = process.env.OCR_ALWAYS_CHANNEL_ID
  ? process.env.OCR_ALWAYS_CHANNEL_ID.split(',').map(id => id.trim())
  : [];
const spoilerChannelId = process.env.SPOILER_CHANNEL_ID
const spoilerRoleId = process.env.SPOILER_ROLE_ID
const spoilerGuildId = process.env.SPOILER_GUILD_ID
const spoilerNoticeChannelId = process.env.SPOILER_NOTICE_CHANNEL_ID
const mysekai_guildId = process.env.MYSEKAI_GUILD_ID
const mysekai_titleChannelId = process.env.MYSEKAI_TITLE_CHANNEL
// OCR APIエンドポイント
const OCR_API_URL = 'http://python-result-calc:53744/ocr';

const mentionDeveloper = process.env.MENTION_USER_USUALLY_YOU

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
    ),
    new SlashCommandBuilder()
    .setName('eventset')
    .setDescription('イベント用のネタバレロールをセットします')
    .addStringOption(option =>
      option.setName('name')
        .setDescription('イベント名')
        .setRequired(true)
    ),
    new SlashCommandBuilder()
    .setName('mysekai-eventset')
    .setDescription('マイセカイコンテスト用のチャンネルをセットします')
    .addStringOption(option =>
      option.setName('name')
        .setDescription('テーマ')
        .setRequired(true)
    )
    .toJSON(),
];

// REST APIクライアントを作成してコマンド登録を実施
const rest = new REST({ version: '10' }).setToken(token);

(async () => {
  try {
    console.log('Started refreshing application (/) commands.');
    if (!clientId || !guildIds.length) {
      console.error('CLIENT_ID または GUILD_ID が設定されていません。');
      return;
    }

    // グローバルにも登録（最大1時間ほど反映にかかる）
    await rest.put(
      Routes.applicationCommands(clientId),
      { body: commands }
    );
    console.log('✅ グローバルコマンドを登録しました。');

  } catch (error) {
    console.error('❌ コマンド登録失敗:', error);
  }
})();

// Botが起動したらログ出力
client.once('clientReady', async () => {
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
    // ここでHTTPステータス確認
    if (!response.ok) {
      console.error(`API HTTPエラー: ${response.status}`);
      return null;
    }

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

const roleIds = process.env.ANNOUNCEMENT_ROLE_IDS
  ? process.env.ANNOUNCEMENT_ROLE_IDS.split(',').map(id => id.trim())
  : [];


async function handleAnnouncementText(text) {
  if (!text) return;

  for (let i = 0; i < channelIds.length; i++) {
    const channelId = channelIds[i];
    const channel = client.channels.cache.get(channelId);
    if (!channel) {
      console.error(`チャンネルが見つかりません: ${channelId}`);
      continue;
    }

    // 対応するロールIDを取得
    const roleId = roleIds[i] || '0'; // デフォルトで無効なID
    const mention = roleId !== '0' ? `<@&${roleId}>` : '@here';

    // 通常メッセージ送信
    await channel.send(`${text}\n\n${mention}`);
  }

  const match = text.match(/(\d+)月(\d+)日(\d+)時(\d+)分より「(プロセカ放送局[^」]+)」/);
  let name, utcStart, utcEnd;
  if (match) {
    const [, month, day, hour, minute, title] = match;
    name = title; // イベント名
    const year = new Date().getFullYear();
    const startDate = new Date(Date.UTC(year, parseInt(month) - 1, parseInt(day), parseInt(hour) - 9, parseInt(minute)));
    utcStart = startDate.toISOString();
    const endDate = new Date(startDate.getTime() + 60 * 60 * 1000);
    utcEnd = endDate.toISOString();

    for (let i = 0; i < guildIds.length; i++) {
      const guildId = guildIds[i];
      if (client.guilds.cache.has(guildId)) {
        const guild = await client.guilds.fetch(guildId);
        const eventChannelId = eventChannelIds[i];
        if (!eventChannelId) {
          console.warn(`⚠️ GUILD_ID=${guildId} に対応するEVENT_CHANNEL_IDが見つかりません。スキップします。`);
          continue;
        }
        const event = await guild.scheduledEvents.create({
          name,
          scheduledStartTime: utcStart,
          scheduledEndTime: utcEnd,
          privacyLevel: GuildScheduledEventPrivacyLevel.GuildOnly,
          entityType: GuildScheduledEventEntityType.Voice,
          channel: eventChannelId,
          description: '「プロセカ放送局」の生配信イベントです。',
        });

        const channelId = channelIds[i];
        const channel = client.channels.cache.get(channelId);
        if (channel) {
          const roleId = roleIds[i] || '0';
          const mention = roleId !== '0' ? `<@&${roleId}>` : '@here';
          await channel.send(`📢 Discordイベントを作成しました！\n${event.url}\n\n${mention}`);
        }

        console.log(`✅ Discordイベント「${name}」を作成しました。`);
      }
    }
  }

  // イベント開催で特定ロールをリセット
  const eventMatch = text.match(/イベント「(.+?)」開催！/);
  if (eventMatch) {
    const eventName = eventMatch[1];

    const guild = await client.guilds.fetch(spoilerGuildId);
    const spoilerNoticeChannel = guild.channels.cache.get(spoilerNoticeChannelId);
    const spoilerChannel = guild.channels.cache.get(spoilerChannelId);
    const role = guild.roles.cache.get(spoilerRoleId);

    if (spoilerNoticeChannel) {
      await spoilerNoticeChannel.send("ネタバレロールをリセットします");
    }

    if (role) {
      // 全メンバーを取得し、ロール所持者のみロールを剥奪
        const membersWithRole = role.members;
      await Promise.all(membersWithRole.map(m => m.roles.remove(role)));
    }

    if (spoilerNoticeChannel) {
      await spoilerNoticeChannel.send("ネタバレチャンネルを更新します");
    }
    if (spoilerChannel) {
      await spoilerChannel.send(`--- ${eventName} ---`);
      await spoilerChannel.setName(`❗｜ネタバレ-${eventName}`);
    }

    if (spoilerNoticeChannel) {
      await spoilerNoticeChannel.send("ネタバレロールを更新します");
    }
    if (role) {
      await role.setName(`${eventName}-ネタバレOK`);
    }

    if (spoilerNoticeChannel) {
      await spoilerNoticeChannel.send(`ネタバレチャンネル・ロールの更新が完了しました。\n「${eventName}」のイベントストーリーを完読した方は再度ロールをつけてください`);
    }
  }


  // マイセカイ百景コンテスント開催で特定ロールをリセット
  const mysekai_eventMatch = text.match(/マイセカイ百景「(.+?)」開催！/);
  if (mysekai_eventMatch) {
    const mysekai_eventName = mysekai_eventMatch[1];

    const mysekai_guild = await client.guilds.fetch(mysekai_guildId);
    const mysekai_titleChannel = mysekai_guild.channels.cache.get(mysekai_titleChannelId);

    if (mysekai_titleChannel) {
      await mysekai_titleChannel.send(`--- ${mysekai_eventName} ---`);
    }
  }
}

// コマンド実行時の処理
client.on('interactionCreate', async interaction => {
  console.log('💬 interactionCreate イベントが発生:', interaction.commandName);
  if (interaction.isChatInputCommand()) {
  if (interaction.commandName === 'nenelobo') {
      await interaction.deferReply({ ephemeral: true });
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
  } else if (interaction.commandName === 'eventset') {
    // 管理者権限チェック
    if (!interaction.member.permissions.has(PermissionsBitField.Flags.Administrator)) {
      await interaction.reply({ content: 'このコマンドは管理者のみが実行できます。', ephemeral: true });
      return;
    }
    await interaction.deferReply({ ephemeral: true });
    const eventName = interaction.options.getString('name');

    // 「イベント開催で特定ロールをリセット」の処理を関数化して呼ぶ
    await resetSpoilerRoleAndChannel(eventName);

    await interaction.editReply(`イベント「${eventName}」のリセット処理を実行しました。`);
  } else if (interaction.commandName === 'mysekai-eventset') {
  // 管理者権限チェック
  if (!interaction.member.permissions.has(PermissionsBitField.Flags.Administrator)) {
    await interaction.reply({ content: 'このコマンドは管理者のみが実行できます。', ephemeral: true });
    return;
  }

  const eventName = interaction.options.getString('name');

  await interaction.deferReply({ ephemeral: true });

  await setMysekaiChannel(eventName);

  await interaction.editReply(`マイセカイ百景「${eventName}」のコンテスト開始処理を実行しました。`);
}
}});

async function resetSpoilerRoleAndChannel(eventName) {
  const guild = await client.guilds.fetch(spoilerGuildId);
  const spoilerNoticeChannel = guild.channels.cache.get(spoilerNoticeChannelId);
  const spoilerChannel = guild.channels.cache.get(spoilerChannelId);
  const role = guild.roles.cache.get(spoilerRoleId);

  if (spoilerNoticeChannel) {
    await spoilerNoticeChannel.send("ネタバレロールをリセットします");
  }

  if (role) {
    const membersWithRole = role.members;
    await Promise.all(membersWithRole.map(m => m.roles.remove(role)));
  }

  if (spoilerNoticeChannel) {
    await spoilerNoticeChannel.send("ネタバレチャンネルを更新します");
  }
  if (spoilerChannel) {
    await spoilerChannel.send(`--- ${eventName} ---`);
    await spoilerChannel.setName(`❗｜ネタバレ-${eventName}`);
  }

  if (spoilerNoticeChannel) {
    await spoilerNoticeChannel.send("ネタバレロールを更新します");
  }
  if (role) {
    await role.setName(`${eventName}-ネタバレOK`);
  }

  if (spoilerNoticeChannel) {
    await spoilerNoticeChannel.send(`ネタバレチャンネル・ロールの更新が完了しました。\n「${eventName}」のイベントストーリーを完読した方は再度ロールをつけてください`);
  }
}

async function setMysekaiChannel(eventName) {
  const mysekai_eventName = eventName;

  const mysekai_guild = await client.guilds.fetch(mysekai_guildId);
  const mysekai_titleChannel = mysekai_guild.channels.cache.get(mysekai_titleChannelId);

  if (mysekai_titleChannel) {
    await mysekai_titleChannel.send(`--- ${mysekai_eventName} ---`);
  }
}

/**
 * =============================================================
 * OCR処理の統合ロジック（最適化版）
 * =============================================================
 * 目的: メンション + 画像、ocrAlwaysChannel の2パターンを
 *      統一ロジックで処理し、DRY原則を実現
 * 
 * 処理フロー:
 *  1. 全画像をPromise.allで並列OCR処理
 *  2. 結果を集約（成功・エラー分離）
 *  3. 総プレイヤー数で表示形式を動的に切り替え
 *     - 1人: メッセージ + スコア絵文字リアクション
 *     - 複数人: Embedテーブル表示（リアクション不要）
 *     - メドレー: ステータス更新メッセージ
 * =============================================================
 */

/**
 * 単一の画像からOCR APIを呼び出す
 */
async function fetchOCRResult(attachmentUrl, options = {}) {
  const { isDebug = false } = options;
  const response = await fetch(attachmentUrl);
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
  return ocrRes.json();
}

/**
 * 複数画像に対して並列OCR処理を実行
 */
async function processMultipleOCR(attachmentUrls, options = {}) {
  const promises = attachmentUrls.map(url => 
    fetchOCRResult(url, options).catch(err => ({
      error: 'API通信エラー',
      details: err.message,
      results: []
    }))
  );
  return Promise.all(promises);
}

/**
 * 全OCR結果を集約して、プレイヤー情報を統合
 * 戻り値: { allPlayers: [{ imageIndex, playerIndex, ...playerData }], errors: [...] }
 */
function aggregateOCRResults(ocrResults) {
  const allPlayers = [];
  const errors = [];

  ocrResults.forEach((result, imageIndex) => {
    if (!result || !result.results) {
      errors.push({ imageIndex, type: 'no_results', message: 'APIレスポンスが無効です' });
      return;
    }

    result.results.forEach((player, playerIndex) => {
      if (player.error) {
        errors.push({ imageIndex, playerIndex, type: 'player_error', message: player.error });
      } else {
        allPlayers.push({ imageIndex, playerIndex, ...player });
      }
    });
  });

  return { allPlayers, errors };
}

/**
 * 1人リザルト用の詳細メッセージと絵文字リアクション
 */
async function sendSinglePlayerResponse(message, player, isDebug = false, ocrResult = null) {
  const reply = [
    `認識結果`,
    `-# ${player.perfect} - ${player.great} - ${player.good} - ${player.bad} - ${player.miss}`,
    `-# 「 ${player.song_title} 」  ${player.song_difficulty}  `,
  ].join('\n');

  const replyMsg = await message.reply(reply);

  // スコア絵文字リアクション
  if (player.score !== undefined) {
    const scoreStr = String(player.score);
    await message.react('<:ocr_score:1389569033874968576>');
    await new Promise(res => setTimeout(res, 500));

    for (let i = 0; i < scoreStr.length; i++) {
      const digit = scoreStr[i];
      const pos = i + 1;
      const emojiId = process.env[`EMOJI_${digit}_${pos}`];
      if (emojiId) {
        await message.react(emojiId);
        await new Promise(res => setTimeout(res, 500));
      }
    }
  }

  // デバッグ画像送信
  if (isDebug && ocrResult) {
    await sendDebugImages(message, ocrResult);
  }

  return replyMsg;
}

/**
 * 複数人リザルト用のEmbed表形式メッセージ
 */
async function sendMultiPlayerResponse(message, players) {
  const fields = ['perfect', 'great', 'good', 'bad', 'miss', 'score'];
  const labels = ['PERFECT(3)', 'GREAT(2)', 'GOOD(1)', 'BAD(0)', 'MISS(0)', 'score'];
  const table = fields.map(() => []);

  players.forEach(player => {
    table[0].push(player.perfect);
    table[1].push(player.great);
    table[2].push(player.good);
    table[3].push(player.bad);
    table[4].push(player.miss);
    table[5].push(player.score);
  });

  let header = '              ' + table[0].map((_, i) => (i + 1).toString().padEnd(4)).join(' ');
  let lines = [header];
  for (let i = 0; i < fields.length; i++) {
    let row = labels[i].padEnd(12) + ': ';
    row += table[i].map(v => String(v).padEnd(4)).join(' ');
    lines.push(row);
  }

  // スコアと精度で順位付け
  const scores = players.map((p, i) => ({
    idx: i + 1,
    score: p.score,
    weight: p.perfect * 1000 + p.great * 10 + p.good * 5 - p.bad * 100 - p.miss * 500
  }));

  scores.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return b.weight - a.weight;
  });

  const rankLines = [];
  let currentRank = 1;
  for (let i = 0; i < scores.length; i++) {
    const { idx } = scores[i];
    const player = `Player_${idx}`;
    if (i > 0 && scores[i].score === scores[i - 1].score && scores[i].weight === scores[i - 1].weight) {
      rankLines.push(`## ${currentRank}位    ${player}（同率）`);
    } else {
      currentRank = i + 1;
      const prefix = currentRank === 1 ? '#' : '##';
      rankLines.push(`${prefix} ${currentRank}位    ${player}`);
    }
  }

  const reply = [
    '### 認識結果',
    '```',
    ...lines,
    '```',
    ...rankLines
  ].join('\n');

  return message.reply(reply);
}

/**
 * デバッグ用画像を送信
 */
async function sendDebugImages(message, ocrResult) {
  if (ocrResult.debug_image_base64) {
    const imageBuffer = Buffer.from(ocrResult.debug_image_base64, 'base64');
    await message.channel.send({
      content: '（デバッグ用）読み取り部分にラベルをつけた画像です:',
      files: [{ attachment: imageBuffer, name: 'labeled_result.png' }]
    });
  }

  if (ocrResult.results && Array.isArray(ocrResult.results)) {
    for (const player of ocrResult.results) {
      if (player.crop_image_base64) {
        const cropBuf = Buffer.from(player.crop_image_base64, 'base64');
        await message.channel.send({
          content: `Player_${player.player} 切り抜き画像`,
          files: [{ attachment: cropBuf, name: `player${player.player}_crop.png` }]
        });
      }

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
        await message.channel.send({
          content: `Player_${player.player} 前処理パラメータ: \n${JSON.stringify(player.preprocess_params, null, 2)}`
        });
      }
    }
  }
}

/**
 * ocrAlwaysChannel用：メドレー計算（複数枚・全て1人リザルト）
 * 
 * 形式:
 * - タイトル: @[ユーザー名] の [枚数]曲メドレースコア
 * - サブタイトル: 現在の日本時刻
 * - メイン: 全画像の合計スコアを大きく表示
 * - 詳細: 「n曲目：曲名 難易度 / スコア / 判定内訳」
 */
async function handleMedleyCalculation(message, allPlayers, ocrResults) {
  const jstNow = new Intl.DateTimeFormat('ja-JP', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    timeZone: 'Asia/Tokyo'
  }).format(new Date());

  // 各画像ごとにプレイヤー情報を整理
  const playersByImage = [];
  for (let i = 0; i < ocrResults.length; i++) {
    const result = ocrResults[i];
    if (result && result.results && result.results.length > 0) {
      playersByImage.push(result.results[0]); // メドレーは各画像1人のみ
    }
  }

  const totalScore = playersByImage.reduce((sum, p) => sum + (p.score || 0), 0);
  const songCount = playersByImage.length;

  const detailLines = playersByImage.map((player, index) => {
    const trackNum = index + 1;
    return [
      `**${trackNum} ** 曲目「 ** ${player.song_title} ** 」${player.song_difficulty}`,
      `-# スコア ${player.score.toLocaleString()} / ${player.perfect} - ${player.great} - ${player.good} - ${player.bad} - ${player.miss}`
    ].join('\n');
  });

  const medleyMessage = [
    `## <@${message.author.id}> の ${songCount}曲メドレースコア`,
    `-# ${jstNow}`,
    '',
    `### 🎵 合計スコア ［${totalScore.toLocaleString()}］`,
    '',
    ...detailLines
  ].join('\n');

  await message.reply(medleyMessage);
}

/**
 * 統合OCR処理ハンドラ（メンション + ocrAlwaysChannel両対応）
 */
async function handleOCRProcessing(message, imageAttachments, options = {}) {
  const { isDebug = false, isMedley = false } = options;

  if (imageAttachments.length === 0) return;

  try {
    // ステップ1: 全画像を並列OCR処理
    const ocrResults = await processMultipleOCR(
      imageAttachments.map(att => att.url),
      { isDebug }
    );

    // ステップ2: 結果を集約
    const { allPlayers, errors } = aggregateOCRResults(ocrResults);

    // エラーログ
    if (errors.length > 0 && !isMedley) {
      console.warn('OCR処理中のエラー:', errors);
    }

    // ステップ3: プレイヤー数に応じた処理分岐
    if (allPlayers.length === 0) {
      // 全て失敗
      await message.react('<:ocr_error_api:1389800393332101311>');
      await message.channel.send(`<@${mentionDeveloper}> OCR処理に失敗しました。`);
      console.error('OCR APIレスポンスが無効です:', ocrResults);
      return;
    }

    if (isMedley) {
      // メドレー計算用（複数枚・全て1人）
      await handleMedleyCalculation(message, allPlayers, imageAttachments);
    } else if (allPlayers.length === 1) {
      // 1人のみ
      await sendSinglePlayerResponse(message, allPlayers[0], isDebug, ocrResults[allPlayers[0].imageIndex]);
    } else {
      // 複数人
      await sendMultiPlayerResponse(message, allPlayers);
    }

  } catch (err) {
    await message.reply('OCR処理中にエラーが発生しました。管理者にご連絡ください。');
    await message.channel.send(`<@${mentionDeveloper}>`);
    console.error('OCR処理の予期しないエラー:', err);
  }
}

/**
 * メンション + 画像の処理
 */
client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (message.mentions.has(client.user, { ignoreEveryone: true }) && message.attachments.size > 0) {
    const isDebug = message.content.toLowerCase().includes('debug');
    const imageAttachments = [...message.attachments.values()].filter(
      att => att.contentType && att.contentType.startsWith('image')
    );

    if (imageAttachments.length > 0) {
      await handleOCRProcessing(message, imageAttachments, { isDebug });
    }
  }
});

/**
 * ocrAlwaysChannel の処理（メドレー計算含む）
 */
client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (ocrAlwaysChannelIds.includes(message.channel.id) && message.attachments.size > 0) {
    const imageAttachments = [...message.attachments.values()].filter(
      att => att.contentType && att.contentType.startsWith('image')
    );

    if (imageAttachments.length === 0) return;

    try {
      // 全てのOCR処理を実行
      const ocrResults = await processMultipleOCR(
        imageAttachments.map(att => att.url),
        { isDebug: false }
      );

      // メドレー判定：複数枚かつ各画像が「ちょうど1人」のリザルトか
      const isMedley = 
        imageAttachments.length >= 2 &&
        ocrResults.every(result => 
          result && result.results && result.results.length === 1 && !result.results[0].error
        );

      if (isMedley) {
        // メドレー計算用
        await handleMedleyCalculation(message, null, ocrResults);
      } else {
        // 通常のOCR処理（複数人リザルトやエラーが含まれている）
        const { allPlayers } = aggregateOCRResults(ocrResults);
        
        if (allPlayers.length === 0) {
          await message.react('<:ocr_error_api:1389800393332101311>');
          await message.channel.send(`<@${mentionDeveloper}> OCR処理に失敗しました。`);
          return; 
        }

        if (allPlayers.length === 1) {
          // 1人のみ
          await sendSinglePlayerResponse(message, allPlayers[0], false, ocrResults[allPlayers[0].imageIndex]);
        } else {
          // 複数人
          await sendMultiPlayerResponse(message, allPlayers);
        }
      }

    } catch (err) {
      await message.reply('OCRが起動していない可能性があります。しばらくしてから再度お試しください。');
      await message.channel.send(`<@${mentionDeveloper}>`);
      console.error(err);
    }
  }
});

// Botトークンでログイン
client.login(token);