import dotenv from 'dotenv';
dotenv.config();

import fs from 'fs';
import fetch from 'node-fetch';
import { EmbedBuilder, Events } from 'discord.js';
import { calculateCombinationProbability } from './gacha.js';

const jstNow = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }));
const currentYear = jstNow.getFullYear();
const BUMP_GACHA_COUNT_FILE = `/app/data/bumpGachaCount${currentYear}.json`;
const NEXT_BUMP_FILE = '/app/data/Nextbump.json';

// スレッドIDの形式: 'チャンネルID/スレッドID' ではなく、スレッド自体のIDを記述（DiscordからスレッドIDを直接取得）
const THREAD_MAP = {
  weekday: {
    '0': process.env.THREAD_WEEKDAY_0,
    '3': process.env.THREAD_WEEKDAY_3,
    '6': process.env.THREAD_WEEKDAY_6,
    '9': process.env.THREAD_WEEKDAY_9,
    '12': process.env.THREAD_WEEKDAY_12,
    '15': process.env.THREAD_WEEKDAY_15,
    '18': process.env.THREAD_WEEKDAY_18,
    '22': process.env.THREAD_WEEKDAY_22
  },
  holiday: {
    '0': process.env.THREAD_HOLIDAY_0,
    '3': process.env.THREAD_HOLIDAY_3,
    '6': process.env.THREAD_HOLIDAY_6,
    '9': process.env.THREAD_HOLIDAY_9,
    '12': process.env.THREAD_HOLIDAY_12,
    '15': process.env.THREAD_HOLIDAY_15,
    '18': process.env.THREAD_HOLIDAY_18,
    '22': process.env.THREAD_HOLIDAY_22
  }
};

const bumpSuccessMessages = [
  /表示順をアップしたよ/,
  /Bump done/,
  /Bump effectué/,
  /Bump fatto/,
  /Podbito serwer/,
  /Успешно поднято/,
  /갱신했어/,
  /Patlatma tamamlandı/
];

function createEmbed(title, description, color = 'Blue') {
  return new EmbedBuilder()
    .setTitle(title)
    .setDescription(description)
    .setColor(color)
    .setTimestamp();
}

function createErrorEmbed(error, context = '不明') {
  return new EmbedBuilder()
    .setTitle('⚠ エラーが発生しました')
    .setDescription(`**状況**: ${context}\n**内容**:\n\`\`\`${error.message}\`\`\``)
    .setColor('Red');
}

// Helper function to read the JSON data from a file
function readJsonFile(filePath) {
  try {
    const data = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(data);
  } catch (err) {
    return {};  // Return empty object if there's an error (e.g., file doesn't exist)
  }
}

// Helper function to write JSON data to a file
function writeJsonFile(filePath, data) {
  try {
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
    console.log(`✅ JSONファイルに書き込み成功: ${filePath}`);
  } catch (error) {
    console.error(`❌ JSONファイルの書き込みに失敗しました: ${filePath}`, error);
  }
}

// 安全にチャンネル名を変更するヘルパー
async function safeSetChannelName(channelOrId, client, newName) {
  try {
    let ch = channelOrId;
    if (typeof channelOrId === 'string') {
      ch = await client.channels.fetch(channelOrId).catch(() => null);
    }
    if (!ch) {
      throw new Error('チャンネルが見つかりません');
    }

    if (typeof ch.setName === 'function') {
      await ch.setName(newName);
    } else if (typeof ch.edit === 'function') {
      await ch.edit({ name: newName });
    } else {
      console.warn('⛔ チャンネルは名前変更APIをサポートしていません');
      return;
    }
    console.log(`チャンネル名が「${newName}」に変更されました`);
  } catch (err) {
    console.error(`名前を「${newName}」に変更中にエラーが発生しました:`, err);
  }
}

// File management for bump gacha
export function handleBumpGacha(message) {
  const bumpGachaCount = readJsonFile(BUMP_GACHA_COUNT_FILE);
  if (!bumpGachaCount.count) bumpGachaCount.count = 0;
  bumpGachaCount.count += 10;  // Increase by 10 per bump

  const results = [];
  // Regular bump gacha draw logic (9 times)
  for (let i = 0; i < 9; i++) {
    const rand = Math.random() * 100;
    if (rand < 88.5) results.push(process.env.EMOJI_STAR2);
    else if (rand < 97) results.push(process.env.EMOJI_STAR3);
    else if (rand < 98.8) results.push(process.env.EMOJI_STAR4);
    else results.push(process.env.EMOJI_STAR4);
  }

  // Last special bump draw logic
  const rand = Math.random() * 100;
  let specialMessage = '';
  if (bumpGachaCount.count % 200 === 0) {
    results.push(process.env.EMOJI_STAR4);  // Pickup Member
    specialMessage = '100% Pickup';
  } else if (bumpGachaCount.count % 100 === 50) {
    if (rand < 98.8) {
      results.push(process.env.EMOJI_STAR4);  // Constant Member
      specialMessage = '98.8% Constant, 1.2% Pickup';
    } else {
      results.push(process.env.EMOJI_STAR4);  // Pickup Member
      specialMessage = '98.8% Constant, 1.2% Pickup';
    }
  } else {
    if (rand < 97) {
      results.push(process.env.EMOJI_STAR3);  // Star3
      specialMessage = '97% Star3, 1.8% Constant, 1.2% Pickup';
    } else if (rand < 98.8) {
      results.push(process.env.EMOJI_STAR4);  // Constant Member
      specialMessage = '97% Star3, 1.8% Constant, 1.2% Pickup';
    } else {
      results.push(process.env.EMOJI_STAR4);  // Pickup Member
      specialMessage = '97% Star3, 1.8% Constant, 1.2% Pickup';
    }
  }

  message.reply(`${specialMessage} - Results: ${results.join(' ')}`);

  // Save updated bump gacha count
  writeJsonFile(BUMP_GACHA_COUNT_FILE, bumpGachaCount);
  console.log(`✅ bumpGachaCount.jsonにガチャ回数を書き込みました: ${bumpGachaCount.count}`);
}

export async function isHoliday(date = new Date()) {
  const year = date.getFullYear();
  const dateStr = date.toISOString().slice(0, 10);
  const url = `https://holidays-jp.github.io/api/v1/${year}/date.json`;

  try {
    const res = await fetch(url);
    const data = await res.json();
    const isNationalHoliday = Object.prototype.hasOwnProperty.call(data, dateStr);
    const isWeekend = date.getDay() === 0 || date.getDay() === 6;
    return isNationalHoliday || isWeekend;
  } catch (err) {
    console.error('🚨 祝日API取得エラー:', err);
    return date.getDay() === 0 || date.getDay() === 6; // API失敗時は週末のみ考慮
  }
}

function getTimeSlotKey(hour) {
  if (hour >= 0 && hour < 3) return '0';
  else if (hour >= 3 && hour < 6) return '3';
  else if (hour >= 6 && hour < 9) return '6';
  else if (hour >= 9 && hour < 12) return '9';
  else if (hour >= 12 && hour < 15) return '12';
  else if (hour >= 15 && hour < 18) return '15';
  else if (hour >= 18 && hour < 22) return '18';
  else if (hour >= 22 && hour < 24) return '22';
  else {
    console.warn(`⛔ 不正なhour値を検出しました: ${hour}。デフォルトで'18'を使用します。`);
    return '18';
  }
}

async function handleBumpSuccess(message, bumpFromMain, bumpTime, guildId) {
  // ① 次のBump可能時間を計算して保存
  const nextBumpDisplayText = `${bumpTime.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} にまたBumpできます`;
  writeJsonFile(NEXT_BUMP_FILE, {
    nextBumpTime: bumpTime.toISOString(),
    nextBumpDisplayText
  });
  console.log(`✅ Nextbump.jsonに次回のBump時間を書き込みました: ${bumpTime.toISOString()}`);

  // ② MAIN_BUMP_CHANNEL_ID に通知を送信
  const mainChannel = await message.client.channels.fetch(process.env.MAIN_BUMP_CHANNEL_ID);
  if (mainChannel) {
    const countdownEmbed = createEmbed(
      'Bumpされたよ！',
      `${nextBumpDisplayText}\n[ここ](https://discord.com/channels/${guildId}/${process.env.MAIN_BUMP_CHANNEL_ID})でお知らせします\nあと 2時間0分0秒`
    );
    const countdownMessage = await mainChannel.send({ embeds: [countdownEmbed] });

    // ③ カウントダウンを開始
    const start = Date.now();
    const duration = 2 * 60 * 60 * 1000;
    updateCountdown(countdownMessage, bumpFromMain, bumpTime, guildId, start, duration, message.client);
  } else {
    console.error('❗ MAIN_BUMP_CHANNEL_ID が見つかりません。');
  }

  // ④ ガチャ結果を確認
    if (!fs.existsSync(BUMP_GACHA_COUNT_FILE)) {
    writeJsonFile(BUMP_GACHA_COUNT_FILE, {
      count: 0,
      star2Total: 0,
      star3Total: 0,
      star4PickupTotal: 0,
      star4ConstantTotal: 0
    });
    specialMessage = 'あけましておめでとうございます！年が変わったのでBumpガチャのカウントをリセットしました。';
  }
  const bumpGachaCount = readJsonFile(BUMP_GACHA_COUNT_FILE);
  if (!bumpGachaCount.count) bumpGachaCount.count = 0;
  bumpGachaCount.count += 1;
  const currentCount = bumpGachaCount.count;
  let specialMessage = '';
  if (currentCount % 20 === 0) {
    specialMessage = '星4ピックアップ確定！';
  } else if (currentCount % 10 === 0 && currentCount % 20 !== 0) {
    specialMessage = '星4確定！（恒常98.8%／ピックアップ1.2%）';
  }

  const gachaHeader = `Bumpガチャ${currentCount}回目`;
  writeJsonFile(BUMP_GACHA_COUNT_FILE, bumpGachaCount);

  // ⑤ ガチャ抽選
  let star2Count = 0;
  let star3Count = 0;
  let star4ConstantCount = 0;
  let star4PickupCount = 0;
  // ① 通常の9回分を抽選
  for (let i = 0; i < 9; i++) {
    const rand = Math.random() * 100;
    if (rand < 88.5) {
      star2Count++;
    } else if (rand < 97) {
      star3Count++;
    } else {
      star4ConstantCount++;
    }
  }
  // ② 特別枠の処理
  let lastResultType = '';
  if (currentCount % 20 === 0) {
    lastResultType = 'star4Pickup';
  } else if (currentCount % 10 === 0) {
    const rand = Math.random() * 100;
    lastResultType = (rand < 98.8) ? 'star4Constant' : 'star4Pickup';
  } else {
    const rand = Math.random() * 100;
    if (star2Count === 9) {
      // ⭐ 9枚すべて星2 → 星3以上を確定で出す（特別抽選）
      if (rand < 97) {
        lastResultType = 'star3';
      } else if (rand < 98.8) {
        lastResultType = 'star4Constant';
      } else {
        lastResultType = 'star4Pickup';
      }
    } else {
      // ⭐ 通常抽選（星2も含む）
      if (rand < 88.5) {
        lastResultType = 'star2';
      } else if (rand < 97) {
        lastResultType = 'star3';
      } else if (rand < 98.8) {
        lastResultType = 'star4Constant';
      } else {
        lastResultType = 'star4Pickup';
      }
    }
  }
  // カウント追加
  if (lastResultType === 'star2') star2Count++;
  else if (lastResultType === 'star3') star3Count++;
  else if (lastResultType === 'star4Constant') star4ConstantCount++;
  else if (lastResultType === 'star4Pickup') star4PickupCount++;

  // ⑥ 星4の内容を評価
  const constantCount = star4ConstantCount;
  const pickupCount = star4PickupCount;

  // --- ここから確率計算 ---
  // lastDrawType: 'star2'|'star3'|'constant'|'pickup' に変換
  let lastDrawType = '';
  if (lastResultType === 'star2') lastDrawType = 'star2';
  else if (lastResultType === 'star3') lastDrawType = 'star3';
  else if (lastResultType === 'star4Constant') lastDrawType = 'constant';
  else if (lastResultType === 'star4Pickup') lastDrawType = 'pickup';

  const draws = [
    star2Count - (lastDrawType === 'star2' ? 1 : 0),
    star3Count - (lastDrawType === 'star3' ? 1 : 0),
    constantCount - (lastDrawType === 'constant' ? 1 : 0),
    pickupCount - (lastDrawType === 'pickup' ? 1 : 0)
  ];
  const prob = calculateCombinationProbability(draws, lastDrawType);
  const percent = (prob * 100).toFixed(4);
  // --- ここまで確率計算 ---

  // ⑦ ガチャ表示文の構築
  const results = [];
  results.push(...Array(star2Count).fill(process.env.EMOJI_STAR2));
  results.push(...Array(star3Count).fill(process.env.EMOJI_STAR3));
  results.push(...Array(star4ConstantCount).fill(process.env.EMOJI_STAR4));
  results.push(...Array(star4PickupCount).fill(process.env.EMOJI_STAR4));
  const gachaResultDisplayText = results.slice(0, 5).join(' ') + '\n' + results.slice(5).join(' ');

  // 新しい評価メッセージ方式
  const summary = [];
  if (constantCount > 0) summary.push(`恒常が${constantCount}枚出ました。`);
  if (pickupCount > 0) summary.push(`ピックアップが${pickupCount}枚出ました。`);
  summary.push(`🎲 この組み合わせが出る確率は約 ${percent}% です。`);
  const evaluationMessageFinal = summary.join('\n');

  // ガチャ結果を MAIN_BUMP_CHANNEL_ID に送信
  if (mainChannel) {
    if (specialMessage) {
      await mainChannel.send(`${gachaHeader}\n${specialMessage}`);
    } else {
      await mainChannel.send(gachaHeader);
    }
    await mainChannel.send(gachaResultDisplayText);
    if (evaluationMessageFinal) {
      await mainChannel.send(evaluationMessageFinal);
    }
  }

  // ⑧ 累計結果を更新
  bumpGachaCount.star2Total = (bumpGachaCount.star2Total || 0) + star2Count;
  bumpGachaCount.star3Total = (bumpGachaCount.star3Total || 0) + star3Count;
  bumpGachaCount.star4PickupTotal = (bumpGachaCount.star4PickupTotal || 0) + pickupCount;
  bumpGachaCount.star4ConstantTotal = (bumpGachaCount.star4ConstantTotal || 0) + constantCount;

  writeJsonFile(BUMP_GACHA_COUNT_FILE, bumpGachaCount);

  // ⑨ 累計結果をDiscordに投稿
  const summaryText =
    `Bumpガチャ累計\n` +
    `> 星2..............${bumpGachaCount.star2Total}枚\n` +
    `> 星3..............${bumpGachaCount.star3Total}枚\n` +
    `> 星4(恒常)...${bumpGachaCount.star4ConstantTotal}枚\n` +
    `> 星4(PU)......${bumpGachaCount.star4PickupTotal}枚`;

  await mainChannel.send(summaryText);
}

export function setupBumpNoticeHandler(client) {
  client.on(Events.MessageCreate, async (message) => {
    const allowedGuildId = process.env.BUMP_SURVEIL_GUILD;
    if (allowedGuildId && message.guildId !== allowedGuildId) return;
    if (message.author.id === '302050872383242240') {
      console.log('📥 Disboard メッセージ検知:', message.embeds[0]?.description || '[内容なし]');
    }

    try {
      const embed = message.embeds?.[0];
      const description = embed?.description;

      if (!description) return;

      // Bump 成功時
      if (
        message.author.id === '302050872383242240' &&
        bumpSuccessMessages.some((regex) => regex.test(description))
      ) {
        console.log('✅ DisboardのBump成功メッセージを検知しました');

        const initialChannelId = process.env.MAIN_BUMP_CHANNEL_ID;
        const bumpFromMain = message.channel.id === initialChannelId;
        const bumpTime = new Date(Date.now() + 2 * 60 * 60 * 1000);
        const guildId = message.guildId;

          try {
            await safeSetChannelName(message.channel, message.client, '🕹｜command');
            console.log('チャンネル名が「🕹｜command」に変更されました！');
          } catch (error) {
            console.error('名前を「🕹｜command」に変更中にエラーが発生しました:', error);
          }

        await handleBumpSuccess(message, bumpFromMain, bumpTime, guildId);

        return;
      }

      // Bump 失敗時
      // NOTE: 現在このメッセージはエフェメラルのためBotからは見えない。
      // ただし将来的にDisboardが仕様変更した場合に備えて残しておく。
      if (description.includes('上げられるようになるまで')) {
        try {
          const minutesMatch = description.match(/と(.+?)分/);
          const remainingMinutes = minutesMatch?.[1]?.trim();

          if (remainingMinutes) {
            await message.channel.send({
              embeds: [
                createEmbed(
                  'Bumpに失敗したようです...',
                  `${remainingMinutes}分後に再度実行できます。`
                )
              ]
            });
            console.log('⚠️ Bump cooldown detected and notification sent.');
          } else {
            throw new Error('残り時間の抽出に失敗しました');
          }
        } catch (error) {
          await message.channel.send({
            embeds: [createErrorEmbed(error, 'Bump失敗時の時間解析')]
          });
        }
      }
    } catch (error) {
      try {
        await message.channel.send({
          embeds: [createErrorEmbed(error, '全体の処理')]
        });
      } catch (fallbackError) {
        console.error('Discordでのエラー通知に失敗:', fallbackError);
        console.error('元のエラー:', error);
      }
    }
  });
  console.log('🟢 BumpNotice handler が有効になりました (messageCreate を監視中)');

  // 内部の sendNextBumpNotification は削除しました。エクスポート済みの関数を使用します。

  const nextBumpData = readJsonFile(NEXT_BUMP_FILE);
  if (nextBumpData.nextBumpTime && new Date(nextBumpData.nextBumpTime) <= new Date()) {
    sendNextBumpNotification(client, new Date(nextBumpData.nextBumpTime), process.env.MAIN_BUMP_CHANNEL_ID);
  } else if (nextBumpData.nextBumpTime && new Date(nextBumpData.nextBumpTime) > new Date()) {
    const { nextBumpTime, guildId } = nextBumpData;
    const start = Date.now();
    const duration = new Date(nextBumpTime).getTime() - start;
    const dummyMessage = { editable: true, edit: async () => {} }; // placeholder message object
    updateCountdown(dummyMessage, false, new Date(nextBumpTime), guildId, start, duration, client);
  }
}

export function setupNextBumpOnStartup(client) {
  const data = readJsonFile(NEXT_BUMP_FILE);
  if (data && data.nextBumpTime) {
    const nextBumpTime = new Date(data.nextBumpTime);
    const now = new Date();

    if (nextBumpTime > now && !data.notified) {
      const delay = nextBumpTime.getTime() - now.getTime();
      const guildId = data.guildId || process.env.BUMP_SURVEIL_GUILD;

      // MAIN_BUMP_CHANNEL_ID に通知を送信
      client.channels.fetch(process.env.MAIN_BUMP_CHANNEL_ID).then(async (mainChannel) => {
        const countdownEmbed = createEmbed(
          '次のBump時間',
          `${nextBumpTime.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} にまたBumpできます\n[ここ](https://discord.com/channels/${guildId}/${process.env.MAIN_BUMP_CHANNEL_ID})でお知らせします\nあと ${Math.floor(delay / 3600000)}時間${Math.floor((delay % 3600000) / 60000)}分`
        );
        const countdownMessage = await mainChannel.send({ embeds: [countdownEmbed] });

        // カウントダウンを開始
        const start = Date.now();
        updateCountdown(countdownMessage, false, nextBumpTime, guildId, start, delay, client);
      }).catch(err => {
        console.error('❗ MAIN_BUMP_CHANNEL_ID が見つかりません:', err);
      });
    }
  }
}

// カウントダウン更新処理を分離
async function updateCountdown(countdownMessage, bumpFromMain, bumpTime, guildId, start, duration, client) {
  let lastDisplayed = '';

  function getNextDelay(secondsLeft) {
    let interval = 1;
    if (secondsLeft > 7140) interval = 2;
    else if (secondsLeft > 3600) interval = 5;
    else if (secondsLeft > 60) interval = 5;
    else interval = 2;
    return 1000 * (secondsLeft % interval || interval);
  }

  async function countdown() {
    const elapsed = Date.now() - start;
    const remaining = Math.max(0, duration - elapsed);
    const secondsLeft = Math.floor(remaining / 1000);

    if (!countdownMessage || !countdownMessage.editable) {
      console.warn('⚠️ メッセージが編集できないため、カウントダウンを中止します。');
      return;
    }

    let displayText = '';
    const h = Math.floor(secondsLeft / 3600);
    const m = Math.floor((secondsLeft % 3600) / 60);
    const s = secondsLeft % 60;

    if (secondsLeft > 3600) {
      displayText = `${h}時間${m}分${s}秒`;
    } else if (secondsLeft > 60) {
      displayText = `${m}分${s}秒`;
    } else {
      displayText = `${s}秒`;
    }

    const nextBump = bumpTime.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });

    const jstDateForLink = new Date(bumpTime.toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }));
    const bumpHourForLink = jstDateForLink.getHours();
    const bumpDayForLink = jstDateForLink.getDay();
    const isHolidayModeForLink = bumpDayForLink === 0 || bumpDayForLink === 6 || await isHoliday(jstDateForLink);
    const timeKeyForLink = getTimeSlotKey(bumpHourForLink);
    const targetIdForLink = (isHolidayModeForLink ? THREAD_MAP.holiday : THREAD_MAP.weekday)[timeKeyForLink];

    const fullText = `${nextBump} にまたBumpできます\n[ここ](https://discord.com/channels/${guildId}/${targetIdForLink})でお知らせします\nあと ${displayText}`;

    if (fullText !== lastDisplayed) {
      try {
        await countdownMessage.edit({
          embeds: [createEmbed(
            bumpFromMain ? 'Bumpありがとう！' : 'Bumpされたよ！',
            fullText
          )]
        });
        lastDisplayed = fullText;
      } catch (err) {
        console.error('⏱ メッセージ更新失敗:', err);
      }
    }

    if (remaining <= 0) {
      // 通知処理
      const nextBumpData = readJsonFile(NEXT_BUMP_FILE);
      if (!nextBumpData.notified) {
          await sendNextBumpNotification(client, bumpTime, process.env.MAIN_BUMP_CHANNEL_ID);
      }
      try {
        if (countdownMessage && typeof countdownMessage.delete === 'function') {
          await countdownMessage.delete();
        }
      } catch (err) {
        console.warn('⚠️ カウントダウンメッセージの削除に失敗しました:', err);
      }
      return;
    }

    const nextDelay = getNextDelay(secondsLeft);
    setTimeout(countdown, nextDelay);
  }

  countdown();
}

// Bumpリマインダー送信処理を分離
async function sendBumpReminder(client, bumpTime, guildId) {
  const jstDate = new Date(bumpTime.toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }));
  const bumpHour = jstDate.getHours();
  const bumpDay = jstDate.getDay();
  const isHolidayMode = bumpDay === 0 || bumpDay === 6 || await isHoliday(jstDate);
  const timeKey = getTimeSlotKey(bumpHour);
  const targetId = (isHolidayMode ? THREAD_MAP.holiday : THREAD_MAP.weekday)[timeKey];
  console.log(`🕵️‍♂️ 通知シミュレーション: JST=${bumpHour}時, 曜日=${bumpDay}, isHoliday=${isHolidayMode}, スレッドキー=${timeKey}, チャンネルID=${targetId}`);

  try {
    const targetChannel = await client.channels.fetch(targetId);
    await targetChannel.send({
      content: '@here',
      embeds: [createEmbed('Bumpできます！', '`/bump` でサーバーの掲載順を上にできます。')]
    });
  } catch (err) {
    console.error('❗ Bumpリマインダー送信失敗（スレッド送信時）:', err);
  }
}

export async function handleNextBumpCommand(interaction, client) {
  try {
    const nextBumpData = readJsonFile(NEXT_BUMP_FILE);
    if (!nextBumpData.nextBumpTime) {
      await interaction.reply({
        content: '次のBump時間の情報が見つかりません。',
        ephemeral: true
      });
      return;
    }

    const nextBumpTime = new Date(nextBumpData.nextBumpTime);
    const now = new Date();

    if (nextBumpTime <= now) {
      await interaction.reply({
        content: 'Bumpできます！`/bump`コマンドを使用してください。',
        ephemeral: true
      });
      return;
    }

    const diffMs = nextBumpTime - now;
    const diffSeconds = Math.floor(diffMs / 1000);
    const hours = Math.floor(diffSeconds / 3600);
    const minutes = Math.floor((diffSeconds % 3600) / 60);
    const seconds = diffSeconds % 60;

    const timeLeft = [];
    if (hours > 0) timeLeft.push(`${hours}時間`);
    if (minutes > 0) timeLeft.push(`${minutes}分`);
    if (seconds > 0) timeLeft.push(`${seconds}秒`);
    const timeLeftStr = timeLeft.join('');

    const jstDate = new Date(nextBumpTime.toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }));
    const bumpHour = jstDate.getHours();
    const bumpDay = jstDate.getDay();
    const isHolidayMode = bumpDay === 0 || bumpDay === 6 || await isHoliday(jstDate);
    const timeKey = getTimeSlotKey(bumpHour);
    const targetId = (isHolidayMode ? THREAD_MAP.holiday : THREAD_MAP.weekday)[timeKey];

    const embedMessage = createEmbed(
      '次のBump時間',
      `${nextBumpTime.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} にBump可能です。\nあと ${timeLeftStr} 待ってください。\n[ここ](https://discord.com/channels/${process.env.BUMP_SURVEIL_GUILD}/${targetId})でお知らせします。`
    );

    // 投稿先をprocess.env.BUMP_SURVEIL_GUILDのメインチャンネルに変更
    const guild = await client.guilds.fetch(process.env.BUMP_SURVEIL_GUILD);
    const mainChannel = await guild.channels.fetch(process.env.MAIN_BUMP_CHANNEL_ID);
    if (mainChannel) {
      await mainChannel.send({ embeds: [embedMessage] });
    } else {
      console.error('❗ メインチャンネルが見つかりません。');
    }

    await interaction.reply({
      content: '次のBump時間をメインチャンネルに投稿しました。',
      ephemeral: true
    });
  } catch (error) {
    await interaction.reply({
      embeds: [createErrorEmbed(error, '/nextbump コマンド実行時のエラー')],
      ephemeral: true
    });
  }
}

// Function to handle the reminder notification based on nextBumpTime
export async function sendNextBumpNotification(client, bumpTime, channel) {
  const jstDate = new Date(bumpTime.toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }));
  const bumpHour = jstDate.getHours();
  const bumpDay = jstDate.getDay();
  const isHolidayMode = bumpDay === 0 || bumpDay === 6 || await isHoliday(jstDate);
  const timeKey = getTimeSlotKey(bumpHour);
  const targetId = (isHolidayMode ? THREAD_MAP.holiday : THREAD_MAP.weekday)[timeKey];

  try {
    const targetChannel = await client.channels.fetch(targetId);
    await targetChannel.send({
      content: '@here',
      embeds: [createEmbed('Bumpできます！', '`/bump` でサーバーの掲載順を上にできます。')]
    });

    // 通知済みフラグを更新
    const nextBumpData = readJsonFile(NEXT_BUMP_FILE);
    nextBumpData.notified = true;
    writeJsonFile(NEXT_BUMP_FILE, nextBumpData);
  } catch (err) {
    console.error('❗ Bumpリマインダー送信失敗（スレッド送信時）:', err);
  }

  // メインチャンネル（または渡されたチャンネル）名を変更し案内を目立たせる
  try {
    await safeSetChannelName(channel, client, '🕹｜「/bump」をお願いします！');
  } catch (err) {
    console.error('名前変更処理でエラーが発生しました:', err);
  }
}