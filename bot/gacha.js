export const performSimpleGachaDraw = (pulls) => {
  const results = [];
  let newMemberCount = 0;
  let slipCount = 0;

  for (let i = 0; i < pulls; i++) {
    const rand = Math.random() * 100;
    if (rand < 88.5) {
      results.push(process.env.EMOJI_STAR2);
    } else if (rand < 97) {
      results.push(process.env.EMOJI_STAR3);
    } else if (rand < 98.8) {
      results.push(process.env.EMOJI_STAR4);
      newMemberCount++;
    } else {
      results.push(process.env.EMOJI_STAR4);
      slipCount++;
    }
  }

  return { results, newMemberCount, slipCount };
};

export function performGacha100() {
  const results = [];
  let star2 = 0, star3 = 0, star4Constant = 0, star4Pickup = 0;

  for (let i = 0; i < 100; i++) {
    const rand = Math.random() * 100;
    let emoji = '';

    if (rand < 88.5) {
      star2++; emoji = process.env.EMOJI_STAR2;
    } else if (rand < 97) {
      star3++; emoji = process.env.EMOJI_STAR3;
    } else if (rand < 98.8) {
      star4Pickup++; emoji = process.env.EMOJI_STAR4;
    } else {
      star4Constant++; emoji = process.env.EMOJI_STAR4;
    }

    const row = Math.floor(i / 10);
    if (!results[row]) results[row] = [];
    results[row].push(emoji);
  }

  return { results, star2, star3, star4Constant, star4Pickup };
}

// 多項分布による確率計算
export function calculateCombinationProbability(draws, lastDrawType) {
  // draws: [star2, star3, constant, pickup] (最初の9回)
  // lastDrawType: 'star2' | 'star3' | 'constant' | 'pickup'
  const n = 9;
  const [x1, x2, x3, x4] = draws;
  const p1 = 0.885, p2 = 0.085, p3 = 0.018, p4 = 0.012;

  // 多項分布
  function factorial(n) {
    let res = 1;
    for (let i = 2; i <= n; i++) res *= i;
    return res;
  }
  const multinom = factorial(n) / (factorial(x1) * factorial(x2) * factorial(x3) * factorial(x4));
  const prob9 = multinom * Math.pow(p1, x1) * Math.pow(p2, x2) * Math.pow(p3, x3) * Math.pow(p4, x4);

  // ラスト1枠の確率
  let probLast = 0;
  if (x1 === 9) {
    // 星2が9枚→星3以上確定
    if (lastDrawType === 'star3') probLast = 0.97 - 0.885; // 0.085
    else if (lastDrawType === 'pickup') probLast = 0.012;
    else if (lastDrawType === 'constant') probLast = 0.018;
    else probLast = 0;
  } else {
    // 通常抽選
    if (lastDrawType === 'star2') probLast = 0.885;
    else if (lastDrawType === 'star3') probLast = 0.085;
    else if (lastDrawType === 'pickup') probLast = 0.012;
    else if (lastDrawType === 'constant') probLast = 0.018;
    else probLast = 0;
  }

  return prob9 * probLast;
}

// 10連ガチャの結果と内訳を返す関数
export function performGacha10() {
  const results = [];
  let star2Count = 0, star3Count = 0, constantCount = 0, pickupCount = 0;

  // 1〜9回目
  for (let i = 0; i < 9; i++) {
    const rand = Math.random() * 100;
    if (rand < 88.5) {
      results.push(process.env.EMOJI_STAR2);
      star2Count++;
    } else if (rand < 97) {
      results.push(process.env.EMOJI_STAR3);
      star3Count++;
    } else if (rand < 98.8) {
      results.push(process.env.EMOJI_STAR4);
      pickupCount++;
    } else {
      results.push(process.env.EMOJI_STAR4);
      constantCount++;
    }
  }

  // 10回目
  let lastDrawType = '';
  const rand = Math.random() * 100;
  if (star2Count === 9) {
    // 星3以上確定
    if (rand < 97) {
      results.push(process.env.EMOJI_STAR3);
      star3Count++;
      lastDrawType = 'star3';
    } else if (rand < 98.8) {
      results.push(process.env.EMOJI_STAR4);
      pickupCount++;
      lastDrawType = 'pickup';
    } else {
      results.push(process.env.EMOJI_STAR4);
      constantCount++;
      lastDrawType = 'constant';
    }
  } else {
    if (rand < 88.5) {
      results.push(process.env.EMOJI_STAR2);
      star2Count++;
      lastDrawType = 'star2';
    } else if (rand < 97) {
      results.push(process.env.EMOJI_STAR3);
      star3Count++;
      lastDrawType = 'star3';
    } else if (rand < 98.8) {
      results.push(process.env.EMOJI_STAR4);
      pickupCount++;
      lastDrawType = 'pickup';
    } else {
      results.push(process.env.EMOJI_STAR4);
      constantCount++;
      lastDrawType = 'constant';
    }
  }

  return {
    results,
    star2Count,
    star3Count,
    constantCount,
    pickupCount,
    lastDrawType
  };
}
