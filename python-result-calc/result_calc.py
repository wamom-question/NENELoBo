#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Result OCR + template-matching module.

This version removes SQLite-based parameter management and switches to:
 - Filesystem-based templates (directory structure)
   /app/data/templates/PERFECT/*.png
   /app/data/templates/MISS/*.png
   Optional per-template metadata sidecar: same basename .json with {"offset_x":int, "offset_y":int}
 - Presets file (JSON) for preprocessing parameter candidates:
   /app/data/presets.json
   If missing, a set of sensible default presets is used.

Behavior:
 - Warmup thread uses the presets to try OCR on images under /app/data/warmup but no DB is used.
 - Template discovery is done by scanning filesystem templates on each call, so updating templates
   is as simple as adding/removing files in the templates directory.
"""

import base64
import glob
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import cv2
import easyocr
import numpy as np
import pytesseract
from flask import Flask, jsonify, request, send_file
from rapidfuzz.distance import Levenshtein

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)

app = Flask(__name__)

# Directories / files
TEMPLATE_DIR = "/app/data/templates"
PRESETS_FILE = "/app/data/presets.json"
WARMUP_DIR = "/app/data/warmup"

# Initialize EasyOCR reader once (non-gpu for portability)
for _ in range(3):
    try:
        reader = easyocr.Reader(["en", "ja"], gpu=False)
        break
    except Exception as e:
        print("Retrying EasyOCR init due to:", e)
        time.sleep(2)
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


def float_to_stored_int(val: float) -> int:
    """Convert float to an easy-to-store int (small utility, preserved for compatibility)."""
    whole = int(val)
    decimal = int((val - whole) * 10)
    return decimal * 10 + whole


def stored_int_to_float(stored: int) -> float:
    """Reverse of float_to_stored_int."""
    whole = stored % 10
    decimal = stored // 10
    return whole + decimal / 10.0


def ensure_dirs_and_files():
    """Ensure template directory and presets file exist. Called from init function."""
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    # Ensure subdirectories for labels exist
    for lbl in ("PERFECT", "MISS"):
        os.makedirs(os.path.join(TEMPLATE_DIR, lbl), exist_ok=True)

    # If presets file missing, create a set of default presets
    if not os.path.exists(PRESETS_FILE):
        default_presets = [
            # conservative preset
            {
                "name": "default_1",
                "threshold": 150,
                "blur": 3,
                "contrast": 1.0,
                "resize_ratio": 1.0,
                "gaussian_blur": 1,
                "use_clahe": False,
            },
            # more aggressive contrast
            {
                "name": "default_2",
                "threshold": 140,
                "blur": 1,
                "contrast": 1.4,
                "resize_ratio": 1.0,
                "gaussian_blur": 0,
                "use_clahe": True,
            },
            # smaller resize
            {
                "name": "default_3",
                "threshold": 160,
                "blur": 5,
                "contrast": 0.9,
                "resize_ratio": 0.8,
                "gaussian_blur": 3,
                "use_clahe": False,
            },
        ]
        try:
            with open(PRESETS_FILE, "w", encoding="utf-8") as f:
                json.dump(default_presets, f, ensure_ascii=False, indent=2)
            logging.info(f"Created default presets at {PRESETS_FILE}")
        except Exception as e:
            logging.warning(f"Failed to write default presets: {e}")


def init_warmup_db():
    """
    Kept name for compatibility with previous callers (gunicorn_conf).
    This now ensures template dirs and presets file exist (no SQLite).
    """
    ensure_dirs_and_files()


def get_presets():
    """Load presets from disk; fall back to in-code defaults if missing/corrupt."""
    try:
        with open(PRESETS_FILE, encoding="utf-8") as f:
            presets = json.load(f)
            if isinstance(presets, list):
                return presets
    except Exception as e:
        logging.warning(f"Could not load presets from {PRESETS_FILE}: {e}")
    # fallback defaults (same as in ensure_dirs_and_files)
    return [
        {
            "name": "default_1",
            "threshold": 150,
            "blur": 3,
            "contrast": 1.0,
            "resize_ratio": 1.0,
            "gaussian_blur": 1,
            "use_clahe": False,
        },
        {
            "name": "default_2",
            "threshold": 140,
            "blur": 1,
            "contrast": 1.4,
            "resize_ratio": 1.0,
            "gaussian_blur": 0,
            "use_clahe": True,
        },
        {
            "name": "default_3",
            "threshold": 160,
            "blur": 5,
            "contrast": 0.9,
            "resize_ratio": 0.8,
            "gaussian_blur": 3,
            "use_clahe": False,
        },
    ]


def warmup_loop():
    """Background loop that periodically runs warmup processing on images under WARMUP_DIR."""
    min_interval = 60
    max_interval = 300
    while True:
        try:
            # frequency heuristic: increase interval if many templates exist
            template_count = sum(
                1
                for _ in glob.iglob(
                    os.path.join(TEMPLATE_DIR, "**", "*.*"), recursive=True
                )
                if os.path.isfile(_)
            )
            ratio = min(template_count / 500.0, 1.0)
            sleep_interval = min_interval + int((max_interval - min_interval) * ratio)
        except Exception:
            sleep_interval = min_interval

        # run warmup
        try:
            warmup_and_check_all_images()
        except Exception as e:
            logging.warning(f"Warmup iteration failed: {e}")

        time.sleep(sleep_interval)


def start_warmup_thread():
    thread = threading.Thread(target=warmup_loop, daemon=True)
    thread.start()


def preprocess_image_for_ocr(
    image, threshold, blur_ksize, contrast, resize_ratio, gaussian_blur_ksize, use_clahe
):
    # Resize
    image = cv2.resize(image, (0, 0), fx=resize_ratio, fy=resize_ratio)

    # Convert to HSV and enhance V channel
    hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    v_channel = hsv_image[:, :, 2]
    v_channel = cv2.equalizeHist(v_channel)
    hsv_image[:, :, 2] = v_channel
    image = cv2.cvtColor(hsv_image, cv2.COLOR_HSV2BGR)

    # Gaussian blur
    if gaussian_blur_ksize and gaussian_blur_ksize > 0:
        k = gaussian_blur_ksize
        if k % 2 == 0:
            k += 1
        image = cv2.GaussianBlur(image, (k, k), 0)

    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Apply simple blur if requested
    if blur_ksize and blur_ksize > 1:
        k = blur_ksize
        if k % 2 == 0:
            k += 1
        gray = cv2.medianBlur(gray, k)

    # Adjust contrast (simple multiplication)
    gray = np.clip((gray.astype(np.float32) * contrast), 0, 255).astype(np.uint8)

    # Threshold (note: original used THRESH_BINARY_INV)
    _, binary_image = cv2.threshold(gray, int(threshold), 255, cv2.THRESH_BINARY_INV)

    if use_clahe:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        binary_image = clahe.apply(binary_image)

    kernel = np.ones((3, 3), np.uint8)
    binary_image = cv2.morphologyEx(binary_image, cv2.MORPH_CLOSE, kernel)

    return binary_image


def _load_templates_from_fs():
    """
    Load templates from the TEMPLATE_DIR.
    Expecting directory structure:
      TEMPLATE_DIR/PERFECT/*.png
      TEMPLATE_DIR/MISS/*.png
    Optional sidecar JSON with same basename (.json) containing {"offset_x":int,"offset_y":int}
    """
    saved_params = []
    for label in ("PERFECT", "MISS"):
        dirpath = os.path.join(TEMPLATE_DIR, label)
        if not os.path.isdir(dirpath):
            continue
        for img_path in sorted(glob.glob(os.path.join(dirpath, "*.*"))):
            # accept common image extensions
            if not img_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                continue
            try:
                template = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
                if template is None:
                    continue
                basename = os.path.splitext(os.path.basename(img_path))[0]
                meta_path = os.path.join(dirpath, basename + ".json")
                offset_x = 0
                offset_y = 0
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, encoding="utf-8") as f:
                            m = json.load(f)
                            offset_x = int(m.get("offset_x", 0))
                            offset_y = int(m.get("offset_y", 0))
                    except Exception:
                        offset_x = 0
                        offset_y = 0
                saved_params.append(
                    {
                        "label": label,
                        "template": template,
                        "offset_x": offset_x,
                        "offset_y": offset_y,
                        "name": basename,
                        "path": img_path,
                    }
                )
            except Exception as e:
                logging.debug(f"Failed to load template {img_path}: {e}")
                continue
    return saved_params


def extract_perfect_miss_positions(image):
    """
    Use filesystem templates to find PERFECT and MISS positions.
    Returns lists of rectangles (x, y, w, h) for perfect_positions, miss_positions
    """

    def detect_positions(img_gray, template, offset_x=0, offset_y=0, threshold=0.8):
        result = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(result >= threshold)
        positions = []
        t_h, t_w = template.shape[:2]
        # merge overlapping detection could be added later; keep simple
        for pt in zip(*loc[::-1]):
            x, y = pt
            positions.append((int(x + offset_x), int(y + offset_y), int(t_w), int(t_h)))
        return positions

    saved_params = _load_templates_from_fs()
    perfect_positions = []
    miss_positions = []

    # Convert search image to grayscale once
    img_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    for param in saved_params:
        label = param["label"]
        template = param["template"]
        offset_x = param.get("offset_x", 0)
        offset_y = param.get("offset_y", 0)
        try:
            positions = detect_positions(img_gray, template, offset_x, offset_y)
        except Exception:
            positions = []
        if label == "PERFECT":
            perfect_positions.extend(positions)
        elif label == "MISS":
            miss_positions.extend(positions)

    return perfect_positions, miss_positions


def blackout_positions(image, positions):
    for x, y, w, h in positions:
        # ensure coordinates within image
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(image.shape[1], x + w)
        y1 = min(image.shape[0], y + h)
        cv2.rectangle(image, (x0, y0), (x1, y1), (0, 0, 0), -1)
    return image


def extract_score_with_easyocr(image):
    # Use the module-level reader
    try:
        results = reader.readtext(image, detail=0)
    except Exception:
        # fallback to pytesseract as last resort
        txt = pytesseract.image_to_string(image, lang="eng")
        results = [l for l in txt.splitlines() if l.strip()]
    numbers = [re.sub(r"\D", "", text) for text in results]
    numbers = [num for num in numbers if num]
    return numbers


def draw_labels(image, perfect_positions, miss_positions, labels=None):
    labeled_image = image.copy()
    for idx, (perfect_pos, miss_pos) in enumerate(
        zip(perfect_positions, miss_positions)
    ):
        _, y_perfect, _, _ = perfect_pos
        _, y_miss, _, h_miss = miss_pos
        base_length = (y_miss + h_miss) - y_perfect
        square_width = int(base_length * 1.3)
        square_height = int(base_length * 1.2)
        x_perfect, y_perfect, _, _ = perfect_pos
        x_label = max(0, x_perfect - int(base_length * 0.1))
        y_label = max(0, y_perfect - int(base_length * 0.1))
        cv2.rectangle(
            labeled_image,
            (x_label, y_label),
            (x_label + square_width, y_label + square_height),
            (0, 255, 0),
            2,
        )
        label_text = labels[idx] if labels and idx < len(labels) else f"{idx + 1}"
        cv2.putText(
            labeled_image,
            label_text,
            (x_label + 5, y_label + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
    return labeled_image


def to_int_safe(value):
    try:
        if isinstance(value, (bytes, bytearray)):
            return int.from_bytes(value, byteorder="little")
        return int(value)
    except Exception:
        return 0


def to_float_safe(value, default=1.0):
    try:
        return float(value)
    except Exception:
        return default


@app.route("/ocr", methods=["POST"])
def ocr_endpoint():
    # Basic checks
    if "image" not in request.files:
        logging.error("No image uploaded")
        return jsonify({"error": "No image uploaded"}), 400

    file = request.files["image"]
    if file.mimetype not in ["image/png", "image/jpeg"]:
        logging.error("Invalid file type")
        return jsonify(
            {"error": "Invalid file type. Only PNG and JPEG are allowed."}
        ), 400
    if file.content_length and file.content_length > 10 * 1024 * 1024:
        logging.error("File too large")
        return jsonify({"error": "File too large. Maximum size is 10MB."}), 400

    try:
        in_memory_file = BytesIO()
        file.save(in_memory_file)
        data = np.frombuffer(in_memory_file.getvalue(), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify({"error": "Could not decode the image."}), 400
    except Exception as e:
        logging.error(f"Error processing image: {e}")
        return jsonify({"error": "An error occurred while processing the image."}), 500

    # Debug flag
    debug_param = request.args.get("debug", request.form.get("debug", "0"))
    debug = str(debug_param).lower() in ("1", "true", "yes")

    # Crop to left-half top area as before to find labels
    song_h, song_w = img.shape[:2]
    song_1left = img[:, : song_w // 2]
    song_2h_left = song_1left.shape[0]
    song_3top_block = song_1left[: song_2h_left // 6, :]
    song_4h_top_block = song_3top_block.shape[0]
    song_5top_under_block = song_3top_block[song_4h_top_block // 2 :, :]

    labels_list = ["EASY", "NORMAL", "HARD", "EXPERT", "MASTER", "APPEND"]
    # find label to align; reuse module reader
    results = reader.readtext(song_5top_under_block)
    found = []
    for bbox, text, conf in results:
        text_up = text.upper()
        if text_up in labels_list:
            x_left = min(p[0] for p in bbox)
            found.append((text_up, x_left, conf))
    if found:
        found.sort(key=lambda x: x[2], reverse=True)
        label, x_local, conf = found[0]
        x_global = x_local - 50
        song_3top_block = song_3top_block[:, max(0, x_global) :]

    # multilingual OCR to find difficulty, level, title
    reader_jp_en = reader  # our reader already initialized with ja,en
    results_full = reader_jp_en.readtext(song_3top_block)
    target_labels = labels_list
    difficulty_info = None
    numeric_candidates = []
    other_texts = []
    for bbox, text, conf in results_full:
        y_center = sum(p[1] for p in bbox) / 4
        text_up = text.upper()
        if text_up in target_labels:
            difficulty_info = (text_up, y_center, bbox)
        else:
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
        if numeric_candidates:
            numeric_candidates.sort(key=lambda x: abs(x[1] - diff_y))
            numeric_text = numeric_candidates[0][0]
            numbers = re.findall(r"\d+", numeric_text)
            song_level = numbers[-1] if numbers else None
        if other_texts:
            other_texts.sort(key=lambda x: abs(x[1] - diff_y), reverse=True)
            target = other_texts[0][0]
            # Use musics.json for best title match if available
            json_file_path = "/app/assets/musics.json"
            best_title = None
            best_distance = float("inf")
            try:
                with open(json_file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    titles = [song.get("title", "") for song in data]
                for title in titles:
                    dist = Levenshtein.distance(target, title)
                    if dist < best_distance:
                        best_distance = dist
                        best_title = title
                song_title = best_title
                logging.info(
                    "曲名: {} (distance: {})".format(song_title, best_distance)
                )
            except Exception:
                song_title = target
    # Resize/crop to canonical size for later template matching
    h, w = img.shape[:2]
    target_w = int(5 / 3 * h)
    target_h = int(3 / 5 * w)
    if w > target_w:
        x_start = (w - target_w) // 2
        img = img[:, x_start : x_start + target_w]
        w = target_w
    if h > target_h:
        y_start = (h - target_h) // 2
        img = img[y_start : y_start + target_h, :]
        h = target_h

    img = cv2.resize(img, (1800, 1080), interpolation=cv2.INTER_AREA)
    processed_img = img.copy()
    all_perfect_positions, all_miss_positions = [], []
    label_regions = []

    # Find perfect/miss positions using templates
    logging.info("Starting template-based perfect/miss detection")
    for _ in range(5):
        perfect_positions, miss_positions = extract_perfect_miss_positions(
            processed_img
        )
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
    logging.info(
        f"Found perfect/miss: {len(all_perfect_positions)} / {len(all_miss_positions)}; label regions: {len(label_regions)}"
    )

    all_player_scores = []
    player_number = 1
    summary_lines = []
    presets = get_presets()

    for region in label_regions:
        logging.info(f"Player_{player_number} region: {region}")
        x_label, y_label, square_width, square_height = region
        crop = img[y_label : y_label + square_height, x_label : x_label + square_width]
        if crop.size == 0:
            logging.warning(f"Player_{player_number}: crop size 0, skipping")
            player_number += 1
            continue
        half = crop.shape[1] // 2
        right_half = crop[:, half : crop.shape[1]]

        ocr_success = False
        debug_crop_b64 = None
        debug_pre_b64 = None
        ocr_text_list = []

        # Try presets in order (filesystem presets)
        for attempt, p in enumerate(presets):
            threshold = to_int_safe(p.get("threshold", 150))
            blur_ksize = to_int_safe(p.get("blur", 1))
            contrast = to_float_safe(p.get("contrast", 1.0))
            resize_ratio = to_float_safe(p.get("resize_ratio", 1.0))
            gaussian_blur_ksize = to_int_safe(p.get("gaussian_blur", 0))
            use_clahe = bool(p.get("use_clahe", False))

            preprocessed_right = preprocess_image_for_ocr(
                right_half,
                threshold,
                blur_ksize,
                contrast,
                resize_ratio,
                gaussian_blur_ksize=gaussian_blur_ksize,
                use_clahe=use_clahe,
            )
            ocr_text_list = extract_score_with_easyocr(preprocessed_right)

            if len(ocr_text_list) >= 5:
                try:
                    perfect_val = int(ocr_text_list[0])
                    great_val = int(ocr_text_list[1])
                    good_val = int(ocr_text_list[2])
                    bad_val = int(ocr_text_list[3])
                    miss_val = int(ocr_text_list[4])

                    if perfect_val == 0 or (
                        perfect_val > 0 and great_val >= perfect_val * 1.5
                    ):
                        # likely misread; skip
                        continue

                    score_raw = (
                        perfect_val * 3
                        + great_val * 2
                        + good_val * 1
                        + bad_val * 0
                        + miss_val * 0
                    )
                    score = math.floor(score_raw)
                    ocr_success = True

                    if debug:
                        _, crop_buf = cv2.imencode(".png", right_half)
                        debug_crop_b64 = base64.b64encode(crop_buf.tobytes()).decode(
                            "utf-8"
                        )
                        _, pre_buf = cv2.imencode(".png", preprocessed_right)
                        debug_pre_b64 = base64.b64encode(pre_buf.tobytes()).decode(
                            "utf-8"
                        )

                    all_player_scores.append(
                        {
                            "song_difficulty": song_difficulty,
                            "song_title": song_title,
                            "player": player_number,
                            "perfect": perfect_val,
                            "great": great_val,
                            "good": good_val,
                            "bad": bad_val,
                            "miss": miss_val,
                            "score": score,
                        }
                    )
                    summary_lines.append(
                        f"Player_{player_number}: OK - PERFECT={perfect_val}, GREAT={great_val}, GOOD={good_val}, BAD={bad_val}, MISS={miss_val}, score={score}"
                    )
                    break
                except Exception as e:
                    logging.warning(
                        f"[Player_{player_number}] parsing OCR result failed: {e}"
                    )
                    continue

        if not ocr_success:
            all_player_scores.append(
                {
                    "player": player_number,
                    "error": "スコア認識に失敗（すべての候補でNG）",
                    "ocr_result": ocr_text_list,
                    **(
                        {
                            "crop_image_base64": debug_crop_b64,
                            "preprocessed_image_base64": debug_pre_b64,
                        }
                        if debug
                        else {}
                    ),
                }
            )
            summary_lines.append(f"Player_{player_number}: 認識失敗")
        player_number += 1

    response = {"results": all_player_scores}
    if debug and label_regions:
        labeled_image = draw_labels(
            img,
            all_perfect_positions,
            all_miss_positions,
            labels=[f"Player_{i + 1}" for i in range(len(label_regions))],
        )
        _, encoded_img = cv2.imencode(".png", labeled_image)
        img_bytes = encoded_img.tobytes()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        response["debug_image_base64"] = img_b64
        response["debug_summary"] = "\n".join(summary_lines)
    return jsonify(response)


# Minimal CLI startup (kept similar to previous behavior)
if __name__ == "__main__":
    logging.info("[Startup] OCR API server starting")
    init_warmup_db()
    logging.info("[Startup] Template/presets initialization done")

    # Do one warmup pass synchronously
    def warmup_and_check_all_images():
        """
        Filesystem-based warmup: iterate a small number of images in WARMUP_DIR and
        exercise the template-matching + OCR pipeline using presets loaded from disk.
        This does not depend on any SQLite DB and only logs a summary.
        """
        if not os.path.isdir(WARMUP_DIR):
            logging.info(f"[Warmup] no warmup directory: {WARMUP_DIR}")
            return 0

        exts = ["*.png", "*.PNG", "*.jpg", "*.JPG", "*.jpeg", "*.JPEG"]
        files = []
        for e in exts:
            files.extend(glob.glob(os.path.join(WARMUP_DIR, e)))
        files = sorted(files)
        if not files:
            logging.info(f"[Warmup] no images found in {WARMUP_DIR}")
            return 0

        np.random.shuffle(files)
        files = files[:10]

        presets = get_presets()
        total = 0
        success = 0

        for fp in files:
            fname = os.path.basename(fp)
            name, _ = os.path.splitext(fname)
            try:
                expected = list(map(int, name.split("-")))
                if len(expected) != 5:
                    logging.debug(f"[Warmup] filename format invalid: {fname}")
                    total += 1
                    continue
            except Exception:
                logging.debug(f"[Warmup] could not parse expected ints from {fname}")
                total += 1
                continue

            img = cv2.imread(fp, cv2.IMREAD_COLOR)
            if img is None:
                logging.debug(f"[Warmup] failed to read: {fp}")
                total += 1
                continue

            # reduce size to keep memory use reasonable
            img = cv2.resize(img, (900, 540), interpolation=cv2.INTER_AREA)

            processed_img = img.copy()
            all_perfect_positions, all_miss_positions = [], []
            for _ in range(5):
                perfect_positions, miss_positions = extract_perfect_miss_positions(
                    processed_img
                )
                all_perfect_positions.extend(perfect_positions)
                all_miss_positions.extend(miss_positions)
                if perfect_positions and miss_positions:
                    break
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

            if not label_regions:
                logging.debug(f"[Warmup] no label regions for {fname}")
                total += 1
                continue

            # test only first label region to keep warmup quick
            x_label, y_label, w_, h_ = label_regions[0]
            crop = img[y_label : y_label + h_, x_label : x_label + w_]
            if crop.size == 0:
                logging.debug(f"[Warmup] empty crop for {fname}")
                total += 1
                continue
            right_half = crop[:, crop.shape[1] // 2 :]

            matched = False
            for p in presets:
                threshold = to_int_safe(p.get("threshold", 150))
                blur_ksize = to_int_safe(p.get("blur", 1))
                contrast = to_float_safe(p.get("contrast", 1.0))
                resize_ratio = to_float_safe(p.get("resize_ratio", 1.0))
                gaussian_blur_ksize = to_int_safe(p.get("gaussian_blur", 0))
                use_clahe = bool(p.get("use_clahe", False))

                pre = preprocess_image_for_ocr(
                    right_half,
                    threshold,
                    blur_ksize,
                    contrast,
                    resize_ratio,
                    gaussian_blur_ksize=gaussian_blur_ksize,
                    use_clahe=use_clahe,
                )
                ocr = extract_score_with_easyocr(pre)
                if len(ocr) >= 5:
                    try:
                        nums = list(map(int, ocr[:5]))
                        if nums == expected:
                            matched = True
                            break
                    except Exception:
                        continue

            total += 1
            if matched:
                success += 1

        logging.info(f"[Warmup] Completed {total} images, success {success}")
        return success

    # Start background warmup thread
    try:
        start_warmup_thread()
        logging.info("[Startup] Warmup thread started")
    except Exception as e:
        logging.warning(f"Failed to start warmup thread: {e}")
    # Start background warmup thread
    try:
        start_warmup_thread()
        logging.info("[Startup] Warmup thread started")
    except Exception as e:
        logging.warning(f"Failed to start warmup thread: {e}")
    app.run(host="0.0.0.0", port=53744)
