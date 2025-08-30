import dotenv from 'dotenv';
dotenv.config();  // .envファイルを読み込む
import fetch from 'node-fetch';
import { promises as fs } from 'fs';
import FormData from 'form-data';

// 環境変数から設定を読み込む
const token = process.env.MINI_DISCORD_TOKEN;
const clientId = process.env.MINI_CLIENT_ID;

// OCR APIエンドポイント
const OCR_API_URL = 'https://nenelobo-calc.wamom.f5.si/ocr';

// スラッシュコマンドの定義
const commands = [
  new SlashCommandBuilder()
    .setName('ping')
    .setDescription('Botの情報を返します。')
    .toJSON(),
  new SlashCommandBuilder()
    .setName('help')
    .setDescription('このBatの使い方')
    .toJSON(),
];

  await rest.put(
    Routes.applicationCommands(clientId),
    { body: commands }
  );
  console.log('✅ グローバルコマンドを登録しました。');

// Botが起動したらログ出力
client.once('ready', async () => {
  console.log('Bot is online!');
});

// コマンド実行時の処理
client.on('interactionCreate', async interaction => {
  console.log('💬 interactionCreate イベントが発生:', interaction.commandName);
  if (interaction.isChatInputCommand()) {
  if (interaction.commandName === 'pitg') {
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
  } else if (interaction.commandName === 'help') {
    // 外部テキストファイルを読み込む
    let helpText;
    try {
      helpText = await fs.readFile('/app/data/help_message.txt', 'utf-8');
    } catch (err) {
      console.error('help_message.txt の読み込みに失敗:', err);
      helpText = 'ヘルプメッセージの読み込みに失敗しました。'; // fallback
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
            await message.reply('APIレスポンスにエラーが発生しました。管理者にご連絡ください。');
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

// Botトークンでログイン
client.login(token);