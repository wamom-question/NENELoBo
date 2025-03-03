require('dotenv').config();  // .envファイルを読み込む

const { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder } = require('discord.js');

// 環境変数から設定を読み込む
const token = process.env.DISCORD_TOKEN;
const clientId = process.env.CLIENT_ID;
const guildId = process.env.GUILD_ID; // テスト用のギルドID

// クライアントの作成（スラッシュコマンド登録のみならGuilds Intentで十分）
const client = new Client({ intents: [GatewayIntentBits.Guilds] });

// スラッシュコマンドの定義（説明付き）
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
    // テスト用のギルド内に登録する場合
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
client.once('ready', () => {
  console.log('Bot is online!');
});

// コマンド実行時の処理
client.on('interactionCreate', async interaction => {
  if (!interaction.isChatInputCommand()) return;
  
  if (interaction.commandName === 'nenelobo') {
    // BotのWebSocket Pingを取得
    const ping = client.ws.ping;
    await interaction.reply(`BotのPingは${ping}msです！`);
  }
});

// Botトークンでログイン
client.login(token);