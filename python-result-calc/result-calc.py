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

logging.basicConfig(
    level=logging.WARN,
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
        min_interval = 5      # 秒
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
    conn = sqlite3.connect(db_path)
    if need_create:
        cursor = conn.cursor()
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
        # テーブルが存在しない場合に備え、念のためチェック＆作成（任意）
        cursor = conn.cursor()
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
    conn.close()
    

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

def warmup_and_check_all_images():
    logging.info("[Debug] warmup_and_check_all_images 開始")
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

        h, w = img.shape[:2]
        target_w = int(5/3 * h)
        target_h = int(3/5 * w)
        if w > target_w:
            x_start = (w - target_w) // 2
            img = img[:, x_start:x_start+target_w]
        if h > target_h:
            y_start = (h - target_h) // 2
            img = img[y_start:y_start+target_h, :]
        img = cv2.resize(img, (1800, 1080), interpolation=cv2.INTER_AREA)

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

        random_prob = get_random_prob(param_db_path)
        if np.random.rand() < random_prob or not rows:
            threshold = np.random.randint(100, 220)
            blur_ksize = np.random.choice([1, 3, 5, 7, 9])
            contrast_scaled = np.random.uniform(0.6, 2.0)
            resize_ratio = np.random.uniform(0.6, 1.6)
            gaussian_blur_ksize = np.random.choice([0, 1, 3, 5, 7, 9])
            use_clahe = np.random.rand() < 0.5
            chosen_row = None
        else:
            total_trials = sum(row[-1] for row in rows) or 1
            best_score = -float('inf')
            chosen_row = None
            for row in rows:
                _, th, bl, ct_scaled, rs_scaled, gb, uc, success_count, total_count = row
                success_count = success_count or 0
                # Skip UCB calculation if total_count is 0 to avoid division by zero
                if not total_count or total_count == 0:
                    continue
                average = success_count / total_count
                ucb_score = average + 1.0 / (1 + total_count) + math.sqrt(2 * math.log(total_trials) / total_count)
                if ucb_score > best_score:
                    best_score = ucb_score
                    chosen_row = row

            _, th, bl, ct_scaled, rs_scaled, gb, uc, _, _ = chosen_row
            contrast_scaled = ct_scaled / 100
            resize_ratio = rs_scaled / 100
            threshold = decode_sqlite_int(th)
            blur_ksize = decode_sqlite_int(bl)
            gaussian_blur_ksize = decode_sqlite_int(gb)
            use_clahe = bool(decode_sqlite_int(uc))

        contrast = int(contrast_scaled * 100)
        resize_ratio_scaled = int(resize_ratio * 100)

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
                logging.info(f"[Debug] OCR結果: {ocr_nums}, 期待値: {expected}")
                if ocr_nums == expected:
                    success = True
                    logging.info("[Debug] スコア一致 → 成功記録処理へ")
                    # 成功パラメータの挿入（存在しなければ）
                    try:
                        conn = sqlite3.connect(param_db_path)
                        c = conn.cursor()
                        logging.info("[Debug] SQLite接続完了（成功）")
                        c.execute("""
                            INSERT OR IGNORE INTO warmup_params (
                                threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe, success_count, total_count
                            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                        """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))
                        logging.info("[Debug] INSERT OR IGNORE 実行")
                        c.execute("""
                            UPDATE warmup_params
                            SET success_count = success_count + 1,
                                total_count = total_count + 1
                            WHERE threshold = ? AND blur = ? AND contrast_scaled = ? AND resize_ratio_scaled = ?
                            AND gaussian_blur = ? AND use_clahe = ?
                        """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))
                        logging.info("[Debug] 成功カウント更新済み")
                        conn.commit()
                        conn.close()
                        logging.info("[Debug] SQLiteコミット・クローズ完了")
                    except Exception as e:
                        logging.warning(f"[Warmup] SQLite成功統計保存失敗: {e}")
            except Exception as e:
                logging.warning(f"[Warmup] 数値変換失敗: {fname} → {ocr_result} → {e}")
                mistake_count += 1

        if not success:
            logging.info("[Debug] スコア一致せず → 失敗処理へ")
            mistake_count += 1

            try:
                conn = sqlite3.connect(param_db_path)
                c = conn.cursor()
                logging.info("[Debug] SQLite接続完了（失敗）")

                if chosen_row:
                    # 既存の行を更新
                    c.execute("""
                        INSERT OR IGNORE INTO warmup_params (
                            threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe, success_count, total_count
                        ) VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                    """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))
                    logging.info("[Debug] INSERT OR IGNORE 実行（失敗）")

                    c.execute("""
                        UPDATE warmup_params
                        SET total_count = total_count + 1
                        WHERE threshold = ? AND blur = ? AND contrast_scaled = ? AND resize_ratio_scaled = ?
                        AND gaussian_blur = ? AND use_clahe = ?
                    """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))
                    logging.info("[Debug] 失敗カウント更新済み")
                else:
                    # 新規ランダム生成パラメータとしてINSERTまたはUPDATE
                    c.execute("""
                        INSERT INTO warmup_params (
                            threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe, success_count, total_count
                        ) VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                        ON CONFLICT(threshold, blur, contrast_scaled, resize_ratio_scaled, gaussian_blur, use_clahe) DO UPDATE SET
                            total_count = total_count + 1
                    """, (threshold, blur_ksize, contrast_scaled, resize_ratio_scaled, gaussian_blur_ksize, int(use_clahe)))
                    logging.info("[Debug] 新規パラメータでINSERTまたはUPDATE（失敗）")

                conn.commit()
                conn.close()
                logging.info("[Debug] SQLiteコミット・クローズ完了（失敗）")
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
    return blurred

def preprocess_image_for_ocr_simple(image):
    gray_result = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray_result, 180, 255, cv2.THRESH_BINARY_INV)
    blurred = cv2.GaussianBlur(thresh, (5, 5), 0)
    return blurred

def extract_perfect_miss_positions(image):
    # 画像がグレースケール（2次元）なら前処理スキップ
    if len(image.shape) == 2:
        preprocessed_img = image.copy()
    else:
        preprocessed_img = preprocess_image_for_ocr_simple(image)
    
    details = pytesseract.image_to_data(preprocessed_img, output_type=pytesseract.Output.DICT)
    all_perfect_positions = []
    all_miss_positions = []
    all_perfect_text_positions = []
    # まずALL PERFECTの位置を探す
    for i, word in enumerate(details['text']):
        if 'ALL' in word.upper():
            if i+1 < len(details['text']) and 'PERFECT' in details['text'][i+1].upper():
                x = details['left'][i]
                y = details['top'][i]
                w = details['width'][i] + details['width'][i+1]
                h = max(details['height'][i], details['height'][i+1])
                all_perfect_text_positions.append((x, y, w, h))
    
    blackout_img = preprocessed_img.copy()
    for (x, y, w, h) in all_perfect_text_positions:
        cv2.rectangle(blackout_img, (x, y), (x + w, y + h), (0, 0, 0), -1)
    
    details2 = pytesseract.image_to_data(blackout_img, output_type=pytesseract.Output.DICT)
    for i, word in enumerate(details2['text']):
        if 'PERFECT' in word.upper():
            (x, y, w, h) = (details2['left'][i], details2['top'][i], details2['width'][i], details2['height'][i])
            all_perfect_positions.append((x, y, w, h))
        if 'MISS' in word.upper():
            (x, y, w, h) = (details2['left'][i], details2['top'][i], details2['width'][i], details2['height'][i])
            all_miss_positions.append((x, y, w, h))
    return all_perfect_positions, all_miss_positions

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

@app.route('/ocr', methods=['POST'])
def ocr_endpoint():
    label_regions = []
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    file = request.files['image']
    debug = request.form.get('debug', '0') == '1'
    in_memory_file = BytesIO()
    file.save(in_memory_file)
    data = np.frombuffer(in_memory_file.getvalue(), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)

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
                CASE WHEN total_count = 0 THEN 0 ELSE CAST(success_count AS FLOAT)/total_count END AS success_rate 
            FROM warmup_params
            WHERE total_count > 0
            ORDER BY success_rate DESC
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
        x_label, y_label, square_width, square_height = region
        crop = img[y_label:y_label+square_height, x_label:x_label+square_width]
        if crop.size == 0:
            player_number += 1
            continue
        half = crop.shape[1] // 2
        right_half = crop[:, half:crop.shape[1]]

        ocr_success = False
        debug_crop_b64 = None
        debug_pre_b64 = None
        debug_params = None

        for attempt, chosen in enumerate(saved_params):
            threshold = to_int_safe(chosen['threshold'])
            blur_ksize = to_int_safe(chosen['blur'])
            contrast = to_float_safe(chosen['contrast_scaled'], 100)
            resize_ratio = to_float_safe(chosen['resize_ratio_scaled'], 100)
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
    _ = reader.readtext(np.ones((100, 300), dtype=np.uint8), detail=0)
    logging.info("[Startup] EasyOCRモデル初期化完了")
    init_warmup_db()
    logging.info("[Startup] ウォームアップDB初期化完了")
    warmup_and_check_all_images()
    logging.info("[Startup] ウォームアップ処理完了")
    start_warmup_thread()
    logging.info("[Startup] ウォームアップスレッド開始")
    logging.info("[Startup] OCR APIサーバー起動")
    app.run(host='0.0.0.0', port=5000)
