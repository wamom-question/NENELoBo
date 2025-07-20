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
import json
import time
import threading
import numpy as np
from io import BytesIO
from datetime import datetime, timedelta, timezone
import random

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',)

app = Flask(__name__)
reader = easyocr.Reader(['en'], gpu=False)

def convert_numpy(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj

def warmup_loop():
    while True:
        now = datetime.now(timezone(timedelta(hours=9)))
        if now.minute % 10 == 0 and now.second == 0:
            warmup_and_check_all_images()
            time.sleep(1)  # 秒ずれ防止
        time.sleep(0.5)

def start_warmup_thread():
    thread = threading.Thread(target=warmup_loop, daemon=True)
    thread.start()

def warmup_and_check_all_images():
    warmup_dir = '/app/data/warmup'
    param_log_path = '/app/data/warmup_success_params.json'
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
    logging.info(f"[Warmup] 開始 {now} / 処理数: {len(png_files)}")

    success_params = []
    mistake_count = 0

    for img_path in png_files:
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
            if not perfect_positions or not miss_positions:
                break
            all_perfect_positions.extend(perfect_positions)
            all_miss_positions.extend(miss_positions)
            processed_img = blackout_positions(processed_img, perfect_positions)
            processed_img = blackout_positions(processed_img, miss_positions)

        label_regions = []
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
            # ε-greedy strategy for parameter selection
            if os.path.exists(param_log_path):
                try:
                    with open(param_log_path, 'r', encoding='utf-8') as f:
                        saved_params = json.load(f)
                except json.JSONDecodeError:
                    saved_params = []
            else:
                saved_params = []

            if saved_params and np.random.rand() < 0.8:
                chosen = random.choice(saved_params)
                threshold = int(chosen['threshold'])
                blur_ksize = int(chosen['blur'])
                contrast = float(chosen['contrast'])
                resize_ratio = float(chosen['resize_ratio'])
            else:
                threshold = np.random.randint(140, 200)
                blur_ksize = np.random.choice([3, 5, 7])
                contrast = np.random.uniform(0.8, 1.5)
                resize_ratio = np.random.uniform(0.8, 1.3)
            preprocessed = preprocess_image_for_ocr(right_half, threshold, blur_ksize, contrast, resize_ratio)
            ocr_result = extract_score_with_easyocr(preprocessed)
            if len(ocr_result) >= 5:
                try:
                    ocr_nums = list(map(int, ocr_result[:5]))
                    if ocr_nums == expected:
                        success_params.append({
                            "image": fname,
                            "threshold": threshold,
                            "blur": blur_ksize,
                            "contrast": round(contrast, 3),
                            "resize_ratio": round(resize_ratio, 3)
                        })
                    else:
                        logging.warning(f"[Warmup] MISMATCH: {fname} → OCR={ocr_nums} / Expected={expected}")
                        mistake_count += 1
                except Exception as e:
                    logging.warning(f"[Warmup] 数値変換失敗: {fname} → {ocr_result} → {e}")
                    mistake_count += 1
            else:
                logging.warning(f"[Warmup] スコア検出失敗: {fname} → {ocr_result}")
            if len(ocr_result) < 5 or (len(ocr_result) >= 5 and ocr_nums != expected):
                mistake_count += 1

    if mistake_count > 0:
        logging.warning(f"[Warmup] 誤認識数: {mistake_count}件")

    if success_params:
        try:
            if os.path.exists(param_log_path):
                try:
                    with open(param_log_path, 'r', encoding='utf-8') as f:
                        old_data = json.load(f)
                except json.JSONDecodeError:
                    logging.warning(f"[Warmup] JSONが不正です。初期化します: {param_log_path}")
                    old_data = []
            else:
                old_data = []

            # numpy型をPython型に変換
            converted_params = json.loads(json.dumps(success_params, default=convert_numpy))
            old_data.extend(converted_params)

            with open(param_log_path, 'w', encoding='utf-8') as f:
                json.dump(old_data, f, indent=2, ensure_ascii=False)
            logging.info(f"[Warmup] 成功パラメータ {len(success_params)} 件保存: {param_log_path}")

            # --- Export as CSV ---
            import csv
            csv_path = '/app/data/warmup_success_params.csv'
            try:
                if os.path.exists(csv_path):
                    os.remove(csv_path)
                with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=['image', 'threshold', 'blur', 'contrast', 'resize_ratio'])
                    writer.writeheader()
                    for row in old_data:
                        writer.writerow(row)
                logging.info(f"[Warmup] CSVも保存しました: {csv_path}")
            except Exception as e:
                logging.warning(f"[Warmup] CSV保存失敗: {e}")
            # --- End CSV export ---
        except Exception as e:
            logging.warning(f"[Warmup] パラメータ保存失敗: {e}")


def preprocess_image_for_ocr(image, threshold=180, blur_ksize=5, contrast=1.0, resize_ratio=1.0):
    img = image.copy()
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
        preprocessed_img = preprocess_image_for_ocr(image)
    details = pytesseract.image_to_data(preprocessed_img, output_type=pytesseract.Output.DICT)
    all_perfect_positions = []
    all_miss_positions = []
    all_perfect_text_positions = []
    # まずALL PERFECTの位置を探す
    for i, word in enumerate(details['text']):
        if 'ALL' in word.upper():
            # 直後にPERFECTが続く場合も考慮
            if i+1 < len(details['text']) and 'PERFECT' in details['text'][i+1].upper():
                x = details['left'][i]
                y = details['top'][i]
                w = details['width'][i] + details['width'][i+1]
                h = max(details['height'][i], details['height'][i+1])
                all_perfect_text_positions.append((x, y, w, h))
    # ALL PERFECTを黒塗り
    blackout_img = preprocessed_img.copy()
    for (x, y, w, h) in all_perfect_text_positions:
        cv2.rectangle(blackout_img, (x, y), (x + w, y + h), (0, 0, 0), -1)
    # 黒塗り後の画像で再度ラベル検出
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

@app.route('/ocr', methods=['POST'])
def ocr_endpoint():
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
        if not perfect_positions or not miss_positions:
            break
        all_perfect_positions.extend(perfect_positions)
        all_miss_positions.extend(miss_positions)
        processed_img = blackout_positions(processed_img, perfect_positions)
        processed_img = blackout_positions(processed_img, miss_positions)
    label_regions = []
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
    for region in label_regions:
        x_label, y_label, square_width, square_height = region
        crop = img[y_label:y_label+square_height, x_label:x_label+square_width]
        if crop.size == 0:
            player_number += 1
            continue
        half = crop.shape[1] // 2
        right_half = crop[:, half:crop.shape[1]]
        ocr_text_list = []
        debug_crop_b64 = None
        debug_pre_b64 = None
        debug_params = None
        player_debug = {}  # debug用の初期化
        for _ in range(10):
            threshold = np.random.randint(140, 200)
            blur_ksize = np.random.choice([3, 5, 7])
            contrast = np.random.uniform(0.8, 1.5)
            resize_ratio = np.random.uniform(0.8, 1.3)
            preprocessed_right = preprocess_image_for_ocr(right_half, threshold, blur_ksize, contrast, resize_ratio)
            ocr_text_list = extract_score_with_easyocr(preprocessed_right)
            if debug and debug_crop_b64 is None:
                _, crop_buf = cv2.imencode('.png', right_half)
                debug_crop_b64 = base64.b64encode(crop_buf.tobytes()).decode('utf-8')
                _, pre_buf = cv2.imencode('.png', preprocessed_right)
                debug_pre_b64 = base64.b64encode(pre_buf.tobytes()).decode('utf-8')
                debug_params = {
                    'threshold': int(threshold),
                    'blur_ksize': int(blur_ksize),
                    'contrast': float(contrast),
                    'resize_ratio': float(resize_ratio)
                }
            if len(ocr_text_list) >= 5:
                break
        if debug:
            player_debug = {
                'crop_image_base64': debug_crop_b64,
                'preprocessed_image_base64': debug_pre_b64,
            }
        if len(ocr_text_list) < 5:
            all_player_scores.append({
                'player': player_number,
                'error': 'スコア認識に失敗',
                'ocr_result': ocr_text_list,
                **player_debug
            })
            summary_lines.append(f"Player_{player_number}: 状態=スコア認識に失敗")
        else:
            try:
                perfect_val = int(ocr_text_list[0])
                great_val   = int(ocr_text_list[1])
                good_val    = int(ocr_text_list[2])
                bad_val     = int(ocr_text_list[3])
                miss_val    = int(ocr_text_list[4])
                # PERFECTが0の場合やGREATがPERFECTの1.5倍以上の場合は再度OCRを試みる
                if perfect_val == 0 or (perfect_val > 0 and great_val >= perfect_val * 1.5):
                    retry_ocr = False
                    for _ in range(5):
                        threshold = np.random.randint(140, 200)
                        blur_ksize = np.random.choice([3, 5, 7])
                        contrast = np.random.uniform(0.8, 1.5)
                        resize_ratio = np.random.uniform(0.8, 1.3)
                        preprocessed_right = preprocess_image_for_ocr(right_half, threshold, blur_ksize, contrast, resize_ratio)
                        retry_ocr_text_list = extract_score_with_easyocr(preprocessed_right)
                        if len(retry_ocr_text_list) >= 5:
                            try:
                                retry_perfect = int(retry_ocr_text_list[0])
                                retry_great   = int(retry_ocr_text_list[1])
                                if retry_perfect != 0 and not (retry_perfect > 0 and retry_great >= retry_perfect * 1.5):
                                    perfect_val = retry_perfect
                                    great_val   = retry_great
                                    good_val    = int(retry_ocr_text_list[2])
                                    bad_val     = int(retry_ocr_text_list[3])
                                    miss_val    = int(retry_ocr_text_list[4])
                                    retry_ocr = True
                                    break
                            except Exception:
                                continue
                    if not retry_ocr:
                        all_player_scores.append({
                            'player': player_number,
                            'error': 'PERFECTが0またはGREATがPERFECTの1.5倍以上のままです',
                            'ocr_result': ocr_text_list,
                            **player_debug
                        })
                        summary_lines.append(f"Player_{player_number}: 状態=PERFECTが0またはGREATがPERFECTの1.5倍以上のままです")
                        player_number += 1
                        continue
                total_notes = perfect_val + great_val + good_val + bad_val + miss_val
                    
                score_raw = (
                    perfect_val * 3 +
                    great_val * 2 +
                    good_val * 1 +
                    bad_val * 0 +
                    miss_val * 0
                )
                score = math.floor(score_raw)
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
            except Exception as e:
                all_player_scores.append({
                    'player': player_number,
                    'error': f'数値変換に失敗: {e}',
                    'ocr_result': ocr_text_list,
                    **player_debug
                })
                summary_lines.append(f"Player_{player_number}: 状態=数値変換に失敗 \n-# 手動で入力してください。")
        player_number += 1

    response = {'results': all_player_scores}
    if len(all_player_scores) == 0:
        logging.error('[OCR API] resultsが空配列です。画像内容や検出ロジックを確認してください。')
        # シンプルな前処理画像で通常の読み取りロジックを再実行
        simple_img = preprocess_image_for_ocr_simple(img)
        if debug:
            _, simple_buf = cv2.imencode('.png', simple_img)
            simple_b64 = base64.b64encode(simple_buf.tobytes()).decode('utf-8')
            response['simple_preprocess_image_base64'] = simple_b64
        # ここから通常の流れ
        processed_img = simple_img.copy()
        all_perfect_positions, all_miss_positions = [], []
        for _ in range(5):
            perfect_positions, miss_positions = extract_perfect_miss_positions(processed_img)
            if not perfect_positions or not miss_positions:
                break
            all_perfect_positions.extend(perfect_positions)
            all_miss_positions.extend(miss_positions)
            processed_img = blackout_positions(processed_img, perfect_positions)
            processed_img = blackout_positions(processed_img, miss_positions)
        label_regions = []
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
        all_player_scores_simple = []
        player_number = 1
        summary_lines_simple = []
        for region in label_regions:
            x_label, y_label, square_width, square_height = region
            crop = img[y_label:y_label+square_height, x_label:x_label+square_width]
            if crop.size == 0:
                player_number += 1
                continue
            half = crop.shape[1] // 2
            right_half = crop[:, half:crop.shape[1]]
            ocr_text_list = []
            for _ in range(10):
                param_log_path = '/app/data/warmup_success_params.json'
                if os.path.exists(param_log_path):
                    try:
                        with open(param_log_path, 'r', encoding='utf-8') as f:
                            saved_params = json.load(f)
                    except json.JSONDecodeError:
                        saved_params = []
                else:
                    saved_params = []

                if saved_params and np.random.rand() < 0.8:
                    chosen = random.choice(saved_params)
                    threshold = int(chosen['threshold'])
                    blur_ksize = int(chosen['blur'])
                    contrast = float(chosen['contrast'])
                    resize_ratio = float(chosen['resize_ratio'])
                else:
                    threshold = np.random.randint(140, 200)
                    blur_ksize = np.random.choice([3, 5, 7])
                    contrast = np.random.uniform(0.8, 1.5)
                    resize_ratio = np.random.uniform(0.8, 1.3)
                preprocessed_right = preprocess_image_for_ocr(right_half, threshold, blur_ksize, contrast, resize_ratio)
                ocr_text_list = extract_score_with_easyocr(preprocessed_right)
                if len(ocr_text_list) >= 5:
                    break
            # ---ここから再OCRロジック---
            retry_ocr = False
            if len(ocr_text_list) >= 5:
                try:
                    perfect_val = int(ocr_text_list[0])
                    great_val   = int(ocr_text_list[1])
                    # 再OCR条件
                    if perfect_val == 0 or (perfect_val > 0 and great_val >= perfect_val * 1.5):
                        max_attempts = 30 if debug else 5
                        for _ in range(max_attempts):
                            threshold = np.random.randint(140, 200)
                            blur_ksize = np.random.choice([3, 5, 7])
                            contrast = np.random.uniform(0.8, 1.5)
                            resize_ratio = np.random.uniform(0.8, 1.3)
                            preprocessed_right = preprocess_image_for_ocr(right_half, threshold, blur_ksize, contrast, resize_ratio)
                            retry_ocr_text_list = extract_score_with_easyocr(preprocessed_right)
                            if len(retry_ocr_text_list) >= 5:
                                try:
                                    retry_perfect = int(retry_ocr_text_list[0])
                                    retry_great   = int(retry_ocr_text_list[1])
                                    if retry_perfect != 0 and not (retry_perfect > 0 and retry_great >= retry_perfect * 1.5):
                                        perfect_val = retry_perfect
                                        great_val   = retry_great
                                        good_val    = int(retry_ocr_text_list[2])
                                        bad_val     = int(retry_ocr_text_list[3])
                                        miss_val    = int(retry_ocr_text_list[4])
                                        ocr_text_list = retry_ocr_text_list
                                        retry_ocr = True
                                        logging.info(f'[Retry-OCR] 成功 threshold={threshold}, blur={blur_ksize}, contrast={contrast:.2f}, resize={resize_ratio:.2f}')
                                        break
                                except Exception:
                                    continue
                    # ---再OCR後の判定---
                    if perfect_val == 0 or (perfect_val > 0 and great_val >= perfect_val * 1.5):
                        all_player_scores_simple.append({
                            'player': player_number,
                            'error': 'PERFECTが0またはGREATがPERFECTの1.5倍以上のままです',
                            'ocr_result': ocr_text_list
                        })
                        summary_lines_simple.append(f"Player_{player_number}: 状態=PERFECTが0またはGREATがPERFECTの1.5倍以上のままです (simple)")
                        player_number += 1
                        continue
                    # ---通常のスコア計算---
                    good_val    = int(ocr_text_list[2])
                    bad_val     = int(ocr_text_list[3])
                    miss_val    = int(ocr_text_list[4])
                    score_raw = (
                        perfect_val * 3 +
                        great_val * 2 +
                        good_val * 1 +
                        bad_val * 0 +
                        miss_val * 0
                    )
                    score = math.floor(score_raw)
                    all_player_scores_simple.append({
                        'player': player_number,
                        'perfect': perfect_val,
                        'great': great_val,
                        'good': good_val,
                        'bad': bad_val,
                        'miss': miss_val,
                        'score': score
                    })
                    summary_lines_simple.append(f"Player_{player_number}: 状態=正常 (simple) \n-# PERFECT={perfect_val}, GREAT={great_val}, GOOD={good_val}, BAD={bad_val}, MISS={miss_val}, スコア={score}")
                except Exception as e:
                    all_player_scores_simple.append({
                        'player': player_number,
                        'error': f'数値変換に失敗 (simple): {e}',
                        'ocr_result': ocr_text_list
                    })
                    summary_lines_simple.append(f"Player_{player_number}: 状態=数値変換に失敗 (simple)")
            else:
                all_player_scores_simple.append({
                    'player': player_number,
                    'error': 'スコア認識に失敗',
                    'ocr_result': ocr_text_list
                })
                summary_lines_simple.append(f"Player_{player_number}: 状態=スコア認識に失敗 (simple) ")
            player_number += 1
        response['results'] = all_player_scores_simple
        # ラベル画像返却（認識できた場合のみ）
        if debug and len(all_player_scores_simple) > 0 and 'error' not in all_player_scores_simple[0]:
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
            response['debug_summary'] = '\n'.join(summary_lines_simple)
        elif debug:
            if 'debug_image_base64' in response:
                del response['debug_image_base64']
    if debug and len(response.get('results', [])) > 0 and 'note' not in response['results'][0]:
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
    warmup_and_check_all_images()
    start_warmup_thread()
    app.run(host='0.0.0.0', port=5000)
