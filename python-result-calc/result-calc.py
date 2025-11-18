from flask import Flask, request, jsonify, send_file
import base64
import cv2
import numpy as np
import easyocr
import pytesseract
import math
import re
import os
import logging
import glob
import time
import threading
import sqlite3
import struct
import numpy as np
from io import BytesIO
from datetime import datetime, timedelta, timezone
import json
from rapidfuzz.distance import Levenshtein

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',)

app = Flask(__name__)
for _ in range(3):
    try:
        reader = easyocr.Reader(['en'], gpu=False)
        break
    except Exception as e:
        print("Retrying due to:", e)
        time.sleep(5)
else:
    raise RuntimeError("EasyOCR initialization failed after multiple attempts")

def convert_numpy(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj

def warmup_loop():
    base_interval = 5  # 初期は5秒間隔でチェック（必要に応じて）
    while True:
        now = datetime.now(timezone(timedelta(hours=9)))

        # 成功レコードの数を確認して間隔を調整
        try:
            conn = sqlite3.connect('/app/data/warmup_success_params.sqlite')
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM warmup_params WHERE success_count >= 2")
            success_count = c.fetchone()[0]
            conn.close()
        except Exception:
            success_count = 0

        # 学習の進み具合に応じて sleep 間隔を変化させる（最大5分まで）
        min_interval = 60      # 秒
        max_interval = 300    # 秒（＝5分）
        max_success = 20000

        # Swap the order so that the condition for max_interval==300 is checked first if needed
        ratio = min(success_count / max_success, 1.0)
        sleep_interval = min_interval + int((max_interval - min_interval) * ratio)

        # 新しい条件ブロック: sleep_interval >= 300 の場合のみ5分ごとのタイミングを厳密にする
        if sleep_interval >= 300:
            if now.minute % 5 == 0 and now.second == 0:
                warmup_and_check_all_images()
                time.sleep(1)  # 秒ずれ防止
        else:
            warmup_and_check_all_images()

        time.sleep(sleep_interval)

def start_warmup_thread():
    thread = threading.Thread(target=warmup_loop, daemon=True)
    thread.start()
    
def init_warmup_db(db_path='/app/data/warmup_success_params.sqlite'):
    need_create = not os.path.exists(db_path)

    # タイムアウトを設定して接続
    conn = sqlite3.connect(db_path, timeout=10)  # 10秒のタイムアウト
    try:
        cursor = conn.cursor()
        
        if need_create:
            cursor.execute('''
                CREATE TABLE warmup_params (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    threshold INTEGER,
                    blur INTEGER,
                    contrast_scaled INTEGER,
                    resize_ratio_scaled INTEGER,
                    gaussian_blur INTEGER,
                    use_clahe INTEGER,
                    success_count INTEGER DEFAULT 0,
                    total_count INTEGER DEFAULT 0,
                    UNIQUE(threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe)
                )
            ''')
            conn.commit()
        else:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='warmup_params'")
            if cursor.fetchone() is None:
                cursor.execute('''
                    CREATE TABLE warmup_params (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        threshold INTEGER,
                        blur INTEGER,
                        contrast_scaled INTEGER,
                        resize_ratio_scaled INTEGER,
                        gaussian_blur INTEGER,
                        use_clahe INTEGER,
                        success_count INTEGER DEFAULT 0,
                        total_count INTEGER DEFAULT 0,
                        UNIQUE(threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe)
                    )
                ''')
                conn.commit()

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    finally:
        cursor.close()  # 明示的にカーソルを閉じる
        conn.close()    # 明示的にコネクションを閉じる

def decode_sqlite_int(val):
    if isinstance(val, bytes):
        return struct.unpack('<q', val)[0]  # SQLite INTEGER は 8バイトリトルエンディアン
    return int(val)

def get_random_prob(param_db_path='/app/data/warmup_success_params.sqlite'):
    try:
        conn = sqlite3.connect(param_db_path)
        c = conn.cursor()
        # 成功回数2回以上のレコード数を取得
        c.execute("SELECT COUNT(*) FROM warmup_params WHERE success_count >= 2")
        count = c.fetchone()[0]
        conn.close()
    except Exception:
        return 1.0
    max_count = 20000
    if count >= max_count:
        return 0.1
    else:
        # 線形に0.9減らす
        return 1.0 - 0.9 * (count / max_count)

def float_to_stored_int(val: float) -> int:
    """小数を逆順で整数に変換（例: 1.2 → 21）"""
    whole = int(val)
    decimal = int((val - whole) * 10)
    return decimal * 10 + whole

def stored_int_to_float(stored: int) -> float:
    """保存された整数を小数に戻す（例: 21 → 1.2）"""
    whole = stored % 10
    decimal = stored // 10
    return whole + decimal / 10

def warmup_and_check_all_images():
    warmup_dir = '/app/data/warmup'
    param_db_path = '/app/data/warmup_success_params.sqlite'
    if not os.path.isdir(warmup_dir):
        logging.warning(f"[Warmup] フォルダが存在しません: {warmup_dir}")
        return

    extensions = ['*.png', '*.PNG', '*.jpg', '*.JPG', '*.jpeg', '*.JPEG']
    png_files = []
    for ext in extensions:
        png_files.extend(glob.glob(os.path.join(warmup_dir, ext)))
    png_files = sorted(png_files)
    if not png_files:
        logging.warning(f"[Warmup] ファイルが見つかりません: {warmup_dir}")
        return

    # ランダムに10枚の画像を選択
    np.random.shuffle(png_files)
    png_files = png_files[:10]

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S')

    mistake_count = 0

    for img_path in png_files:
        label_regions = []
        fname = os.path.basename(img_path)
        name, _ = os.path.splitext(fname)
        try:
            expected = list(map(int, name.split('-')))
            if len(expected) != 5:
                logging.warning(f"[Warmup] 無効なファイル名形式: {fname}")
                mistake_count += 1
                continue
        except Exception as e:
            logging.warning(f"[Warmup] ファイル名解析失敗: {fname} → {e}")
            mistake_count += 1
            continue

        img = cv2.imread(img_path, cv2.IMREAD_COLOR)
        if img is None:
            logging.warning(f"[Warmup] 読み込み失敗: {fname}")
            mistake_count += 1
            continue

        # 解像度を下げてメモリ使用量を削減
        img = cv2.resize(img, (900, 540), interpolation=cv2.INTER_AREA)

        processed_img = img.copy()
        all_perfect_positions, all_miss_positions = [], []
        for _ in range(5):
            perfect_positions, miss_positions = extract_perfect_miss_positions(processed_img)
            all_perfect_positions.extend(perfect_positions)
            all_miss_positions.extend(miss_positions)
            if perfect_positions and miss_positions:
                break
            processed_img = blackout_positions(processed_img, perfect_positions)
            processed_img = blackout_positions(processed_img, miss_positions)
        for perfect_pos, miss_pos in zip(all_perfect_positions, all_miss_positions):
            x_perfect, y_perfect, _, _ = perfect_pos
            _, y_miss, _, h_miss = miss_pos
            base_length = (y_miss + h_miss) - y_perfect
            square_width = int(base_length * 1.3)
            square_height = int(base_length * 1.2)
            x_label = max(0, x_perfect - int(base_length * 0.1))
            y_label = max(0, y_perfect - int(base_length * 0.1))
            label_regions.append((x_label, y_label, square_width, square_height))
        label_regions.sort(key=lambda r: r[0])

        if not label_regions:
            logging.warning(f"[Warmup] ラベル領域が0件のためスキップ: {fname}")
            mistake_count += 1
            continue
        for region in label_regions:
            x, y, w_, h_ = region
            crop = img[y:y+h_, x:x+w_]
            if crop.size == 0:
                continue
            right_half = crop[:, crop.shape[1]//2:]

        success = False

        # SQLiteからパラメータ候補を取得
        if os.path.exists(param_db_path):
            conn = sqlite3.connect(param_db_path)
            c = conn.cursor()
            c.execute("SELECT id, threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe, success_count, total_count FROM warmup_params")
            rows = c.fetchall()
            conn.close()
        else:
            rows = []

        # 既存パラメータを元に探索精度を段階的に広げる
        expanded_rows = []
        # 定数の定義
        MAX_SUCCESS_COUNT = 30  # 実績の十分な基準値

        # 成功率計算式の修正
        for row in rows:
            row_id, th, bl, contrast_scaled, resize_ratio_scaled, gb, uc, success_count, total_count = row
            if total_count == 0:
                continue
            
            effective_success = min(success_count, MAX_SUCCESS_COUNT)
            success_rate = (success_count / total_count) * (success_count / (success_count + 5))

            # 0.1単位の基本行は常に含める
            expanded_rows.append(row)

            # 条件に応じて精度を上げて追加
            if total_count >= 10 and success_rate > 0.6:
                for delta_c in [-5, 0, 5]:
                    for delta_r in [-5, 0, 5]:
                        new_contrast_scaled = contrast_scaled + delta_c  # 0.01単位で調整（×100）
                        new_resize_ratio_scaled = resize_ratio_scaled + delta_r
                        if (delta_c != 0 or delta_r != 0):
                            expanded_rows.append((
                                row_id, th, bl, new_contrast_scaled, new_resize_ratio_scaled, gb, uc, success_count, total_count
                            ))
        rows = expanded_rows

        chosen_row = None

        rand_val = np.random.rand()
        use_ucb = rand_val < 0.2 and rows # 20%の確率でUCBを使用
        use_low_count = 0.2 <= rand_val < 0.6 and rows # 40%の確率で低カウント優先、残りはランダム

        if use_ucb:
            total_trials = sum(row[-1] for row in rows) or 1
            best_score = -float('inf')
            best_rows = []
            
            for row in rows:
                _, th, bl, contrast_scaled, resize_ratio_scaled, gb, uc, success_count, total_count = row
                if total_count == 0 or (success_count == 0 and total_count > 10):
                    continue

                average = success_count / total_count
                weight = success_count / (success_count + 5)
                weighted_average = average * weight

                ucb_score = (
                    weighted_average +
                    1.0 / (1 + total_count) +
                    math.sqrt(2 * math.log(total_trials) / total_count)
                )

                if ucb_score > best_score:
                    best_score = ucb_score
                    best_rows = [row]
                elif ucb_score == best_score:
                    best_rows.append(row)

            if best_rows:
                chosen_row = best_rows[np.random.randint(len(best_rows))]
        
        elif use_low_count:
            # トータルカウントが少ない順にソートして上位100個からランダム選択
            sorted_rows = sorted(rows, key=lambda r: r[8])  # total_countがインデックス8
            top_100 = sorted_rows[:100]
            if top_100:
                chosen_row = top_100[np.random.randint(len(top_100))]

        if chosen_row:
            _, th, bl, contrast_scaled, resize_ratio_scaled, gb, uc, _, _ = chosen_row
            contrast = stored_int_to_float(contrast_scaled)
            resize_ratio = stored_int_to_float(resize_ratio_scaled)
            threshold = decode_sqlite_int(th)
            blur_ksize = decode_sqlite_int(bl)
            gaussian_blur_ksize = decode_sqlite_int(gb)
            use_clahe = bool(decode_sqlite_int(uc))
        else:
            threshold = np.random.randint(100, 220)
            blur_ksize = np.random.choice([1, 3, 5, 7, 9])
            contrast = np.random.uniform(0.6, 2.0)
            resize_ratio = np.random.uniform(0.6, 1.6)
            gaussian_blur_ksize = np.random.choice([0, 1, 3, 5, 7, 9])
            use_clahe = np.random.rand() < 0.5

        contrast_scaled = float_to_stored_int(contrast)
        resize_ratio_scaled = float_to_stored_int(resize_ratio)

        # OCR処理
        preprocessed = preprocess_image_for_ocr(
            right_half, threshold, blur_ksize, contrast, resize_ratio,
            gaussian_blur_ksize=gaussian_blur_ksize, use_clahe=use_clahe
        )
        ocr_result = extract_score_with_easyocr(preprocessed)
        # 結果確認
        if len(ocr_result) >= 5:
            try:
                ocr_nums = list(map(int, ocr_result[:5]))
                if ocr_nums == expected:
                    success = True
                    # 成功パラメータの挿入（存在しなければ）
                    try:
                        conn = sqlite3.connect(param_db_path)
                        c = conn.cursor()
                        c.execute("""
                            INSERT OR IGNORE INTO warmup_params (
                                threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe, success_count, total_count
                            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                        """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))
                        c.execute("""
                            UPDATE warmup_params
                            SET success_count = success_count + 1,
                                total_count = total_count + 1
                            WHERE threshold = ? AND blur = ? AND contrast_scaled = ? AND resize_ratio_scaled = ?
                            AND gaussian_blur = ? AND use_clahe = ?
                        """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))
                        conn.commit()
                        conn.close()
                    except Exception as e:
                        logging.warning(f"[Warmup] SQLite成功統計保存失敗: {e}")
            except Exception as e:
                mistake_count += 1

        if not success:
            mistake_count += 1

            try:
                conn = sqlite3.connect(param_db_path)
                c = conn.cursor()

                if chosen_row:
                    # 既存の行を更新
                    c.execute("""
                        INSERT OR IGNORE INTO warmup_params (
                            threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe, success_count, total_count
                        ) VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                    """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))

                    c.execute("""
                        UPDATE warmup_params
                        SET total_count = total_count + 1
                        WHERE threshold = ? AND blur = ? AND contrast_scaled = ? AND resize_ratio_scaled = ?
                        AND gaussian_blur = ? AND use_clahe = ?
                    """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))
                else:
                    # 新規ランダム生成パラメータとしてINSERTまたはUPDATE
                    c.execute("""
                        INSERT INTO warmup_params (
                            threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe, success_count, total_count
                        ) VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                        ON CONFLICT(threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe) DO UPDATE SET
                            total_count = total_count + 1
                    """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))

                conn.commit()
                conn.close()
            except Exception as e:
                logging.warning(f"[Warmup] SQLite失敗統計更新失敗: {e}")

def preprocess_image_for_ocr(image, threshold, blur_ksize, contrast, resize_ratio, gaussian_blur_ksize, use_clahe):
    img = image.copy()
    if img is None:
        print("画像読み込みに失敗しました")
        return None
    if img.size == 0:
        print("画像サイズが0です")
        return None
    if resize_ratio != 1.0:
        img = cv2.resize(img, None, fx=resize_ratio, fy=resize_ratio, interpolation=cv2.INTER_LINEAR)
    hsv_image = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lower_bg1 = np.array([100, 20, 90])
    upper_bg1 = np.array([140, 50, 140])
    lower_bg2 = np.array([130, 20, 70])
    upper_bg2 = np.array([180, 50, 120])
    mask_bg1 = cv2.inRange(hsv_image, lower_bg1, upper_bg1)
    mask_bg2 = cv2.inRange(hsv_image, lower_bg2, upper_bg2)
    combined_mask = cv2.bitwise_or(mask_bg1, mask_bg2)
    result = cv2.bitwise_and(img, img, mask=cv2.bitwise_not(combined_mask))
    result[combined_mask != 0] = [255, 255, 255]
    gray_result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
    gray_result = cv2.convertScaleAbs(gray_result, alpha=contrast, beta=0)
    _, thresh = cv2.threshold(gray_result, threshold, 255, cv2.THRESH_BINARY_INV)
    if blur_ksize > 1:
        blurred = cv2.GaussianBlur(thresh, (blur_ksize, blur_ksize), 0)
    else:
        blurred = thresh
    del hsv_image, mask_bg1, mask_bg2, combined_mask  # メモリ解放
    return blurred

def preprocess_image_for_ocr_simple(image):
    gray_result = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray_result, 180, 255, cv2.THRESH_BINARY_INV)
    blurred = cv2.GaussianBlur(thresh, (5, 5), 0)
    return blurred

def extract_perfect_miss_positions(image):
    def get_saved_params():
        saved_params = []
        db_path = '/app/data/warmup_success_params.sqlite'
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT *, 
                    CASE WHEN total_count = 0 THEN 0 ELSE CAST(success_count AS FLOAT)/total_count END AS success_rate 
                FROM warmup_params
                WHERE total_count > 0
                ORDER BY success_rate DESC
                LIMIT 10
            """)
            saved_params = [dict(row) for row in cur.fetchall()]
            conn.close()
        except Exception as e:
            logging.warning(f"[extract] SQLite 読み込み失敗: {e}")
        return saved_params

    def detect_positions(img):
        details = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        perfect_positions = []
        miss_positions = []
        perfect_text_positions = []

        for i, word in enumerate(details['text']):
            if 'ALL' in word.upper():
                if i+1 < len(details['text']) and 'PERFECT' in details['text'][i+1].upper():
                    x = details['left'][i]
                    y = details['top'][i]
                    w = details['width'][i] + details['width'][i+1]
                    h = max(details['height'][i], details['height'][i+1])
                    perfect_text_positions.append((x, y, w, h))

        blackout_img = img.copy()
        for (x, y, w, h) in perfect_text_positions:
            cv2.rectangle(blackout_img, (x, y), (x + w, y + h), (0, 0, 0), -1)

        details2 = pytesseract.image_to_data(blackout_img, output_type=pytesseract.Output.DICT)
        for i, word in enumerate(details2['text']):
            if 'PERFECT' in word.upper():
                (x, y, w, h) = (details2['left'][i], details2['top'][i], details2['width'][i], details2['height'][i])
                perfect_positions.append((x, y, w, h))
            if 'MISS' in word.upper():
                (x, y, w, h) = (details2['left'][i], details2['top'][i], details2['width'][i], details2['height'][i])
                miss_positions.append((x, y, w, h))
        return perfect_positions, miss_positions

    # 1回目（簡易前処理）
    if len(image.shape) == 2:
        preprocessed_img = image.copy()
    else:
        preprocessed_img = preprocess_image_for_ocr_simple(image)
    perfects, misses = detect_positions(preprocessed_img)
    if perfects or misses:
        return perfects, misses

    # 2回目（SQLiteからパラメータ取得して再前処理）
    saved_params = get_saved_params()

    def to_int_safe(val):
        if isinstance(val, bytes):
            return int.from_bytes(val, byteorder='little')
        return int(val)

    for params in saved_params:
        try:
            blur_ksize = to_int_safe(params.get('blur', 0))
            threshold = to_int_safe(params.get('threshold', 128))
            contrast_scaled = to_int_safe(params.get('contrast_scaled', 10))
            resize_ratio_scaled = to_int_safe(params.get('resize_ratio_scaled', 10))
            contrast = stored_int_to_float(contrast_scaled)
            resize_ratio = stored_int_to_float(resize_ratio_scaled)
            gaussian_blur = to_int_safe(params.get('gaussian_blur', 0))
            use_clahe = bool(params.get('use_clahe', False))

            processed = preprocess_image_for_ocr(
                image, threshold, blur_ksize, contrast, resize_ratio,
                gaussian_blur_ksize=gaussian_blur, use_clahe=use_clahe
            )
            perfects, misses = detect_positions(processed)
            if perfects or misses:
                return perfects, misses
        except Exception as e:
            logging.warning(f"[extract retry] 再処理エラー: {e}")

    return [], []

def blackout_positions(image, positions):
    for (x, y, w, h) in positions:
        cv2.rectangle(image, (x, y), (x + w, y + h), (0, 0, 0), -1)
    return image

def extract_score_with_easyocr(image):
    results = reader.readtext(image, detail=0)
    numbers = [re.sub(r'\D', '', text) for text in results]
    numbers = [num for num in numbers if num]
    return numbers

def draw_labels(image, perfect_positions, miss_positions, labels=None):
    labeled_image = image.copy()
    for idx, (perfect_pos, miss_pos) in enumerate(zip(perfect_positions, miss_positions)):
        _, y_perfect, _, h_perfect = perfect_pos
        _, y_miss, _, h_miss = miss_pos
        base_length = (y_miss + h_miss) - y_perfect
        square_width = int(base_length * 1.3)
        square_height = int(base_length * 1.2)
        x_perfect, y_perfect, _, _ = perfect_pos
        x_label = max(0, x_perfect - int(base_length * 0.1))
        y_label = max(0, y_perfect - int(base_length * 0.1))
        cv2.rectangle(labeled_image, (x_label, y_label), (x_label + square_width, y_label + square_height), (0, 255, 0), 2)
        label_text = labels[idx] if labels and idx < len(labels) else f"{idx+1}"
        cv2.putText(labeled_image, label_text, (x_label + 5, y_label + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    return labeled_image

def to_int_safe(value):
    if isinstance(value, bytes):
        return int.from_bytes(value, byteorder='little')
    return int(value)

def to_float_safe(value, scale=1.0):
    if isinstance(value, bytes):
        return int.from_bytes(value, byteorder='little') / scale
    return float(value) / scale

def get_easyocr_reader():
    try:
        return easyocr.Reader(['en'], gpu=False)
    except Exception as e:
        logging.error(f"EasyOCRの初期化に失敗しました: {e}")
        raise

@app.route('/ocr', methods=['POST'])
def ocr_endpoint():
    label_regions = []
    logging.info("ラベル領域初期化")
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    file = request.files['image']
    debug = request.form.get('debug', '0') == '1'
    in_memory_file = BytesIO()
    file.save(in_memory_file)
    data = np.frombuffer(in_memory_file.getvalue(), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)

    logging.info(f"画像読み込み成功: img.shape={img.shape if img is not None else 'None'}")
    song_h, song_w = img.shape[:2]
    song_1left = img[:, :song_w // 2]
    song_2h_left = song_1left.shape[0]
    song_3top_block = song_1left[:song_2h_left // 6, :]
    song_4h_top_block = song_3top_block.shape[0]
    song_5top_under_block = song_3top_block[song_4h_top_block // 2:, :]

    labels = ["EASY", "NORMAL", "HARD", "EXPERT", "MASTER", "APPEND"]
    reader = easyocr.Reader(['en'])

    results = reader.readtext(song_5top_under_block)

    found = []
    for (bbox, text, conf) in results:
        text_up = text.upper()
        if text_up in labels:
            # bbox = [ [x1,y1], [x2,y2], [x3,y3], [x4,y4] ]
            x_left = min(p[0] for p in bbox)
            found.append((text_up, x_left, conf))

    # 最も確度の高いラベルを取る
    if found:
        found.sort(key=lambda x: x[2], reverse=True)
        label, x_local, conf = found[0]

        # song_5top_under_block の原点が song_3top_block 由来であることを反映
        # song_3top_block は song_1left の [0 : song_2h_left//6, :]
        # song_1left は img の [:, :song_w//2]
        x_global = x_local - 50  # 左半分の中での X → 元画像でも同じ

        # x_local を基準に song_3top_block を右端まで切り抜く
        song_3top_block = song_3top_block[:, x_global:]

            # 日本語 + 英語モードで song_3top_block を OCR し、3つのラベル（難易度・レベル値・曲名）を抽出
    reader_jp_en = easyocr.Reader(['ja', 'en'])
    results_full = reader_jp_en.readtext(song_3top_block)

    target_labels = ["EASY", "NORMAL", "HARD", "EXPERT", "MASTER", "APPEND"]

    difficulty_info = None
    numeric_candidates = []
    other_texts = []

    for (bbox, text, conf) in results_full:
        y_center = sum(p[1] for p in bbox) / 4
        text_up = text.upper()

        if text_up in target_labels:
            difficulty_info = (text_up, y_center, bbox)
        else:
            # 数字ラベル候補
            if re.fullmatch(r"\d+(\.\d+)?", text.strip()):
                numeric_candidates.append((text.strip(), y_center, bbox))
            else:
                other_texts.append((text.strip(), y_center, bbox))

    song_difficulty = None
    song_level = None
    song_title = None

    if difficulty_info:
        _, diff_y, _ = difficulty_info
        song_difficulty = difficulty_info[0]

        # レベル（数字）は難易度と最も y が近いもの
        if numeric_candidates:
            numeric_candidates.sort(key=lambda x: abs(x[1] - diff_y))
            numeric_text = numeric_candidates[0][0]
            numbers = re.findall(r"\d+", numeric_text)
            song_level = numbers[-1] if numbers else None

        # 曲名は難易度と最も y が遠いもの
        if other_texts:
            other_texts.sort(key=lambda x: abs(x[1] - diff_y), reverse=True)
            target = other_texts[0][0]

        titles = []
        json_file_path = '/app/assets/musics.json'

        # JSONファイルを読み込む
        with open(json_file_path, encoding='utf-8') as f:
            data = json.load(f)
            titles = [song["title"] for song in data] 
        
        best_title = None
        best_distance = float("inf")

        for title in titles:
            dist = Levenshtein.distance(target, title)  # 通常のレーベンシュタイン距離
            if dist < best_distance:
                best_distance = dist
                best_title = title
        song_title = best_title
        logging.info("曲名: {} (精度: {})".format(song_title, best_distance))
             
    else:
        label, x_local, x_global = None, None, None
        song_difficulty = None
        song_level = None
        song_title = None

    # 画像のアスペクト比を調整して中央切り抜き
    h, w = img.shape[:2]
    target_w = int(5/3 * h)
    target_h = int(3/5 * w)
    if w > target_w:
        # 幅が広すぎる場合、中央から target_w の幅で切り抜き
        x_start = (w - target_w) // 2
        img = img[:, x_start:x_start+target_w]
        w = target_w
    if h > target_h:
        # 高さが高すぎる場合、中央から target_h の高さで切り抜き
        y_start = (h - target_h) // 2
        img = img[y_start:y_start+target_h, :]
        h = target_h
    # 1800x1080にリサイズ
    img = cv2.resize(img, (1800, 1080), interpolation=cv2.INTER_AREA)
    processed_img = img.copy()
    all_perfect_positions, all_miss_positions = [], []
    logging.info("perfect/miss 抽出処理開始")
    for _ in range(5):
        perfect_positions, miss_positions = extract_perfect_miss_positions(processed_img)
        all_perfect_positions.extend(perfect_positions)
        all_miss_positions.extend(miss_positions)
        if perfect_positions and miss_positions:
            break
        processed_img = blackout_positions(processed_img, perfect_positions)
        processed_img = blackout_positions(processed_img, miss_positions)
    for perfect_pos, miss_pos in zip(all_perfect_positions, all_miss_positions):
        x_perfect, y_perfect, _, _ = perfect_pos
        _, y_miss, _, h_miss = miss_pos
        base_length = (y_miss + h_miss) - y_perfect
        square_width = int(base_length * 1.3)
        square_height = int(base_length * 1.2)
        x_label = max(0, x_perfect - int(base_length * 0.1))
        y_label = max(0, y_perfect - int(base_length * 0.1))
        label_regions.append((x_label, y_label, square_width, square_height))
    label_regions.sort(key=lambda r: r[0])
    logging.info(f"抽出された perfect/miss の数: {len(all_perfect_positions)} / {len(all_miss_positions)}")
    logging.info(f"生成されたラベル領域数: {len(label_regions)}")
    if not label_regions:
        logging.warning("ラベル領域が 0 件だったためスコア認識処理をスキップします")
    all_player_scores = []
    player_number = 1
    summary_lines = []

    # SQLiteから最も安定しているパラメータを取得（成功率＝success_count/total_countが最大）
    saved_params = []
    db_path = '/app/data/warmup_success_params.sqlite'
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # 成功率でソート（total_count=0防止にCASE文）、上位10件取得
        cur.execute("""
            SELECT *, 
                CASE 
                    WHEN total_count = 0 THEN 0 
                    ELSE (CAST(success_count AS FLOAT) / total_count) *
                        (CAST(success_count AS FLOAT) / (success_count + 5))
                END AS weighted_score
            FROM warmup_params
            WHERE total_count > 5
            ORDER BY weighted_score DESC
            LIMIT 10
        """)
        saved_params = [dict(row) for row in cur.fetchall()]
        conn.close()
        if not saved_params:
            raise ValueError("安定したパラメータが見つかりません")
    except Exception as e:
        logging.warning(f"[Retry-OCR] 成功パラメータDB読み込み失敗または未取得: {e}")
        saved_params = []

    # パラメータがある場合はそれらを順に使う（最大10件）
    for region in label_regions:
        logging.info(f"Player_{player_number} の領域開始: {region}")
        x_label, y_label, square_width, square_height = region
        crop = img[y_label:y_label+square_height, x_label:x_label+square_width]
        if crop.size == 0:
            logging.warning(f"Player_{player_number}: crop.size == 0 でスキップされました")
            player_number += 1
            continue
        half = crop.shape[1] // 2
        right_half = crop[:, half:crop.shape[1]]

        ocr_success = False
        debug_crop_b64 = None
        debug_pre_b64 = None

        for attempt, chosen in enumerate(saved_params):
            threshold = to_int_safe(chosen['threshold'])
            blur_ksize = to_int_safe(chosen['blur'])
            contrast = stored_int_to_float(chosen['contrast_scaled'])
            resize_ratio = stored_int_to_float(chosen['resize_ratio_scaled'])
            gaussian_blur_ksize = to_int_safe(chosen.get('gaussian_blur', 0))
            use_clahe = bool(chosen.get('use_clahe', False))

            preprocessed_right = preprocess_image_for_ocr(
                right_half,
                threshold,
                blur_ksize,
                contrast,
                resize_ratio,
                gaussian_blur_ksize=gaussian_blur_ksize,
                use_clahe=use_clahe
            )
            ocr_text_list = extract_score_with_easyocr(preprocessed_right)

            if len(ocr_text_list) >= 5:
                try:
                    perfect_val = int(ocr_text_list[0])
                    great_val = int(ocr_text_list[1])
                    good_val = int(ocr_text_list[2])
                    bad_val = int(ocr_text_list[3])
                    miss_val = int(ocr_text_list[4])

                    if perfect_val == 0 or (perfect_val > 0 and great_val >= perfect_val * 1.5):
                        continue

                    score_raw = (
                        perfect_val * 3 +
                        great_val * 2 +
                        good_val * 1 +
                        bad_val * 0 +
                        miss_val * 0
                    )
                    score = math.floor(score_raw)
                    ocr_success = True

                    if debug:
                        _, crop_buf = cv2.imencode('.png', right_half)
                        debug_crop_b64 = base64.b64encode(crop_buf.tobytes()).decode('utf-8')
                        _, pre_buf = cv2.imencode('.png', preprocessed_right)
                        debug_pre_b64 = base64.b64encode(pre_buf.tobytes()).decode('utf-8')
                        debug_params = {
                            'threshold': threshold,
                            'blur_ksize': blur_ksize,
                            'contrast': round(contrast, 3),
                            'resize_ratio': round(resize_ratio, 3),
                            'gaussian_blur': gaussian_blur_ksize,
                            'use_clahe': use_clahe
                        }

                    all_player_scores.append({
                        'song_difficulty': song_difficulty,
                        'song_title': song_title,
                        'player': player_number,
                        'perfect': perfect_val,
                        'great': great_val,
                        'good': good_val,
                        'bad': bad_val,
                        'miss': miss_val,
                        'score': score
                    })
                    summary_lines.append(f"Player_{player_number}: 状態=正常 \n-# PERFECT={perfect_val}, GREAT={great_val}, GOOD={good_val}, BAD={bad_val}, MISS={miss_val}, スコア={score}")
                    break
                except Exception as e:
                    logging.warning(f"[Player_{player_number}] OCR試行中に例外が発生（attempt={attempt}）: {e}")
                    continue

        if not ocr_success:
            all_player_scores.append({
                'player': player_number,
                'error': 'スコア認識に失敗（すべての候補でNG）',
                'ocr_result': ocr_text_list,
                **({'crop_image_base64': debug_crop_b64, 'preprocessed_image_base64': debug_pre_b64} if debug else {})
            })
            summary_lines.append(f"Player_{player_number}: 状態=認識失敗")
        player_number += 1

    response = {'results': all_player_scores}
    if debug and label_regions:
        # 通常処理で認識できた場合のみラベル画像を返す
        labeled_image = draw_labels(
            img,
            all_perfect_positions,
            all_miss_positions,
            labels=[f"Player_{i+1}" for i in range(len(label_regions))]
        )
        _, encoded_img = cv2.imencode('.png', labeled_image)
        img_bytes = encoded_img.tobytes()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')
        response['debug_image_base64'] = img_b64
        response['debug_summary'] = '\n'.join(summary_lines)
    elif debug and len(response.get('results', [])) > 0 and response['results'][0].get('note') == 'simple preprocess fallback':
        # シンプル下処理で認識できた場合は上記で枠線画像を返す（summaryは空）
        response['debug_summary'] = 'simple preprocess fallback'
    return jsonify(response)

if __name__ == '__main__':
    # EasyOCRモデルの初期化を遅延実行に変更
    logging.info("[Startup] OCR APIサーバー起動")
    init_warmup_db()
    logging.info("[Startup] ウォームアップDB初期化完了")
    warmup_and_check_all_images()
    logging.info("[Startup] ウォームアップ処理完了")
    start_warmup_thread()
    logging.info("[Startup] ウォームアップスレッド開始")
    app.run(host='0.0.0.0', port=53744)