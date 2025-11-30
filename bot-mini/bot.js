import dotenv from 'dotenv';
dotenv.config();  // .envファイルを読み込む
import fetch from 'node-fetch';
import { promises as fs } from 'fs';
import FormData from 'form-data';
import { REST } from '@discordjs/rest';
import { Routes, SlashCommandBuilder, EmbedBuilder, Client, GatewayIntentBits, Colors } from 'discord.js';

// 環境変数から設定を読み込む
const token = process.env.MINI_DISCORD_TOKEN;
const clientId = process.env.MINI_CLIENT_ID;
const adminChannelId = process.env.MINI_ADMIN_CHANNEL_ID; // optional: channel to post admin notifications
const adminUserId = process.env.MINI_ADMIN_USER_ID; // optional: user to DM for admin notifications

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent
  ]
});

// OCR APIエンドポイント
const OCR_API_URL = process.env.OCR_API_URL || 'https://nenelobo-calc.wamom.f5.si/ocr';

const rest = new REST({ version: '10' }).setToken(token);
// スラッシュコマンドの定義
const commands = [
  new SlashCommandBuilder()
    .setName('ping')
    .setDescription('Botのpingを返します。')
    .toJSON(),
  new SlashCommandBuilder()
    .setName('help')
    .setDescription('このBotの使い方')
    .toJSON(),
  new SlashCommandBuilder()
    .setName('report')
    .setDescription('不具合報告や認識結果が間違っていた場合はこちらから')
    .toJSON()
];

// register global commands with error handling
try {
  if (!clientId) throw new Error('MINI_CLIENT_ID is not set');
  await rest.put(Routes.applicationCommands(clientId), { body: commands });
  console.log('✅ グローバルコマンドを登録しました。');
} catch (err) {
  console.error('グローバルコマンド登録に失敗しました:', err);
  // sendAdminNotification is declared later (function declaration hoisting ensures it's available)
  try { sendAdminNotification && sendAdminNotification(`グローバルコマンド登録に失敗しました: ${err && err.message ? err.message : String(err)}`); } catch (e) { console.error('sendAdminNotification failed:', e); }
}

// Botが起動したらログ出力
// Notification queue: hold messages until the bot is ready
const _adminNotificationQueue = [];

/**
 * Send admin notification to configured channel or user. Will queue if client isn't ready.
 * Uses function declaration so it's hoisted and callable earlier.
 */
async function sendAdminNotification(content, options = {}) {
  const payload = { content };
  if (options.embed) payload.embeds = [options.embed];
  try {
    if (client && client.isReady && client.isReady()) {
      if (adminChannelId) {
        const ch = await client.channels.fetch(adminChannelId).catch(() => null);
        if (ch && ch.send) return ch.send(payload).catch(err => console.error('admin channel send failed:', err));
      }
      if (adminUserId) {
        const u = await client.users.fetch(adminUserId).catch(() => null);
        if (u && u.send) return u.send(payload).catch(err => console.error('admin user send failed:', err));
      }
    }
  } catch (err) {
    console.error('sendAdminNotification immediate attempt failed:', err);
  }
  // fallback: queue for sending later
  _adminNotificationQueue.push(payload);
}

client.once('ready', async () => {
  console.log('Bot is online!');
  // Flush queued admin notifications
  while (_adminNotificationQueue.length > 0) {
    const p = _adminNotificationQueue.shift();
    try {
      if (adminChannelId) {
        const ch = await client.channels.fetch(adminChannelId).catch(() => null);
        if (ch && ch.send) await ch.send(p).catch(err => console.error('flushed send failed:', err));
        continue;
      }
      if (adminUserId) {
        const u = await client.users.fetch(adminUserId).catch(() => null);
        if (u && u.send) await u.send(p).catch(err => console.error('flushed user send failed:', err));
      }
    } catch (err) {
      console.error('Failed flushing admin notification:', err);
    }
  }
});

// コマンド実行時の処理
client.on('interactionCreate', async interaction => {
  try {
    console.log('💬 interactionCreate イベントが発生:', interaction.commandName);
    if (interaction.isChatInputCommand()) {
      if (interaction.commandName === 'ping') {
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
      .setColor(Colors.Blue)
      .setTitle('📶 Ping 結果')
      .setDescription(replacedText)
      .setTimestamp();

    await interaction.reply({ embeds: [embed] });
      } else if (interaction.commandName === 'help') {
        // handled below in same logic
      }
    }
  } catch (err) {
    console.error('interactionCreate handler failed:', err);
    try { await sendAdminNotification(`interaction handler error: ${err && err.message ? err.message : String(err)}`); } catch (e) { console.error('notify failed:', e); }
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
          // download attachment with timeout
          const ac = new AbortController();
          const dlTimeout = setTimeout(() => ac.abort(), 15000);
          const response = await fetch(attachment.url, { signal: ac.signal }).catch(err => { throw err; });
          clearTimeout(dlTimeout);
          if (!response || !response.ok) throw new Error(`attachment download failed status=${response ? response.status : 'no response'}`);
          const arrayBuffer = await response.arrayBuffer();
          const buffer = Buffer.from(arrayBuffer);

          const form = new FormData();
          form.append('image', buffer, { filename: 'image.png', contentType: 'image/png' });
          form.append('debug', isDebug ? '1' : '0');

          // OCR request with timeout
          const ocrAc = new AbortController();
          const ocrTimeout = setTimeout(() => ocrAc.abort(), 30000);
          const ocrRes = await fetch(OCR_API_URL, {
            method: 'POST',
            body: form,
            headers: form.getHeaders(),
            signal: ocrAc.signal
          }).catch(err => { throw err; });
          clearTimeout(ocrTimeout);

          const contentType = ocrRes && ocrRes.headers && ocrRes.headers.get ? ocrRes.headers.get('content-type') : '';
          const text = await ocrRes.text();
          console.log('OCR content-type:', contentType);
          console.log('OCR response (truncated 1000 chars):', text.slice(0, 1000));
          let result = null;
          try { result = JSON.parse(text); } catch (err) {
            const short = text.length > 1000 ? text.slice(0, 1000) + '...[truncated]' : text;
            const msg = `OCR API returned invalid JSON. status=${ocrRes.status} content-type=${contentType} body=${short}`;
            console.error(msg, err);
            await message.reply('OCR APIの応答が予期しない形式でした。管理者に通知しました。');
            await sendAdminNotification(msg);
            continue;
          }

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

              // スコアと精度で順位付け（①スコア優先、③同点なら同順位）
              const scores = result.results.map((p, i) => ({
                idx: i + 1,
                score: p.score,
                weight: p.perfect * 1000 + p.great * 10 + p.good * 5 - p.bad * 100 - p.miss * 500
              }));

              // スコア → 重み付き精度 でソート
              scores.sort((a, b) => {
                if (b.score !== a.score) return b.score - a.score;
                return b.weight - a.weight;
              });

              const rankLines = [];
              let currentRank = 1;
              for (let i = 0; i < scores.length; i++) {
                const { idx, score, weight } = scores[i];
                const player = `Player_${idx}`;
                if (i > 0 && scores[i].score === scores[i - 1].score && scores[i].weight === scores[i - 1].weight) {
                  // 同点なら順位維持（③）
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
              await message.reply(reply);
            } else {
              // 1人だけなら従来通り
              let reply = result.results.map(player => {
                if (player.error) {
                    return `Player_${player.player}: 認識失敗 (${player.error})  [エラー報告](https://docs.google.com/forms/d/e/1FAIpQLScqHbtMLhsVUS69ckg5QSXRTAhTJ4hJsKKyjmpGLLEnL7jxXw/viewform?usp=header)をお願いします。`;
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
                    `## ランクマスコア  ${player.score}`,
                    `-# 「 ${player.song_title} 」  ${player.song_difficulty} `
                  ].join('\n');
                }
              }).join('\n\n');
              await message.reply(reply);
            }
          } else {
            const errMsg = 'APIレスポンスにエラーが発生しました。resultsが無い、または空配列でした。';
            console.error(errMsg, result);
            await message.reply(`${errMsg} 管理者に通知しました。`);
            await sendAdminNotification(`${errMsg} raw=${JSON.stringify(result).slice(0,1000)}`);
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
          console.error('OCR処理中に例外が発生しました:', err);
          try { await message.reply('OCR処理中にエラーが発生しました。管理者に通知しました。'); } catch (e) { console.error('reply failed:', e); }
          await sendAdminNotification(`OCR処理中の例外: ${err && err.stack ? err.stack : String(err)}`);
        }
      }
    }
  }
});

// Botトークンでログイン
// Global process-level error handlers
process.on('unhandledRejection', async (reason, promise) => {
  console.error('Unhandled Rejection at:', promise, 'reason:', reason);
  try { await sendAdminNotification(`UnhandledRejection: ${reason && reason.stack ? reason.stack : String(reason)}`); } catch (e) { console.error('notify failed:', e); }
});

process.on('uncaughtException', async (err) => {
  console.error('Uncaught Exception:', err);
  try { await sendAdminNotification(`UncaughtException: ${err && err.stack ? err.stack : String(err)}`); } catch (e) { console.error('notify failed:', e); }
  // Do not exit automatically here; allow restart manager to handle restarts if desired
});

if (!token) {
  console.error('MINI_DISCORD_TOKEN is not set. Bot will not login.');
  sendAdminNotification && sendAdminNotification('MINI_DISCORD_TOKEN is not set; bot failed to start.');
} else {
  client.login(token).catch(async (err) => {
    console.error('client.login failed:', err);
    await sendAdminNotification(`Bot login failed: ${err && err.message ? err.message : String(err)}`);
  });
}