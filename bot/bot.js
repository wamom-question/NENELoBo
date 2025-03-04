import dotenv from 'dotenv';
dotenv.config();  // .envファイルを読み込む

import { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder } from 'discord.js';
import fetch from 'node-fetch';

// 環境変数から設定を読み込む
const token = process.env.DISCORD_TOKEN;
const clientId = process.env.CLIENT_ID;
const channelId = process.env.ANNOUNCEMENT_CHANNEL_ID;  // お知らせを送るチャンネルID
const guildId = process.env.GUILD_ID; // テスト用のギルドID
const ANNOUNCEMENT_API = process.env.ANNOUNCEMENT_API || 'http://python_app:5000/announcements'; // PythonのAPIエンドポイント

// クライアントの作成
const client = new Client({ intents: [GatewayIntentBits.Guilds] });

// スラッシュコマンドの定義
const commands = [
  new SlashCommandBuilder()
    .setName('nenelobo')
    .setDescription('BotのPingを返します。')
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
  setTimeout(() => {
    sendAnnouncements(); // 少し遅延してから送信
  }, 5000);  // 5秒の遅延を追加
  setInterval(sendAnnouncements, 60 * 1000); // 1分間隔で実行
});

async function sendAnnouncements() {
  try {
    const response = await fetch('http://python_app:5000/announcements');
    const text = await response.text();
    console.log(`API Response: ${text}`);

    if (text.trim() !== "新しいお知らせはありません。") {
      const channel = client.channels.cache.get(channelId);
      if (channel) {
        channel.send(text);
      } else {
        console.error('チャンネルが見つかりません。');
      }
    }
  } catch (error) {
    console.error(`API 接続エラー: ${error.message}`);
  }
}

// コマンド実行時の処理
client.on('interactionCreate', async interaction => {
  if (!interaction.isChatInputCommand()) return;
  
  if (interaction.commandName === 'nenelobo') {
    const ping = client.ws.ping;
    await interaction.reply(`BotのPingは${ping}msです！`);
  }
});

// Botトークンでログイン
client.login(token);