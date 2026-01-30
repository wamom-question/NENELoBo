import cv2
import numpy as np

def extract_perfect_miss_positions(image):
    def get_saved_params():
        saved_params = []
        db_path = "/app/data/warmup_success_params.sqlite"
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT *,
                    CASE WHEN total_count = 0 THEN 0 ELSE CAST(success_count AS FLOAT)/total_count 
            FROM warmup_success_params
            """)
            rows = cur.fetchall()
            for row in rows:
                saved_params.append({
                    'label': row['label'],
                    'template': cv2.imread(row['template_path'], cv2.IMREAD_GRAYSCALE),
                    'offset_x': row['offset_x'],
                    'offset_y': row['offset_y']
                })
        except sqlite3.Error as e:
            print(f"SQLite error: {e}")
        return saved_params

    def detect_positions(img, template):
        result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        threshold = 0.8
        loc = np.where(result >= threshold)
        positions = []
        for pt in zip(*loc[::-1]):
            x, y = pt
            positions.append((x + offset_x, y + offset_y))
        return positions

    def to_int_safe(val):
        try:
            return int(val)
        except ValueError:
            return 0

    saved_params = get_saved_params()
    perfect_positions = []
    miss_positions = []

    for param in saved_params:
        label = param['label']
        template = param['template']
        offset_x = param['offset_x']
        offset_y = param['offset_y']

        positions = detect_positions(image, template)
        if label == 'PERFECT':
            perfect_positions.extend(positions)
        elif label == 'MISS':
            miss_positions.extend(positions)

    return perfect_positions, miss_positions

def blackout_positions(image, positions):
    for x, y in positions:
        cv2.rectangle(image, (x - 10, y - 10), (x + 50, y + 50), (0, 0, 0), -1)
    return image

def extract_score_with_easyocr(image):
    # EasyOCRの処理を削除
    pass

def draw_labels(image, perfect_positions, miss_positions, labels=None):
    for x, y in perfect_positions:
        cv2.putText(image, 'PERFECT', (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
    for x, y in miss_positions:
        cv2.putText(image, 'MISS', (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
    return image

def to_int_safe(value):
    try:
        return int(value)
    except ValueError:
        return 0

def to_float_safe(value, scale=1.0):
    try:
        return float(value) * scale
    except ValueError:
        return 0.0

def get_easyocr_reader():
    # EasyOCRのリーダーを削除
    pass

@app.route("/ocr", methods=["POST"])
def ocr_endpoint():
    if request.method == "POST":
        file = request.files['image']
        image = cv2.imdecode(np.frombuffer(file.read(), np.uint8), cv2.IMREAD_COLOR)
        perfect_positions, miss_positions = extract_perfect_miss_positions(image)
        result_image = blackout_positions(image, perfect_positions + miss_positions)
        result_image = draw_labels(result_image, perfect_positions, miss_positions)

        _, encoded_image = cv2.imencode('.png', result_image)
        response = make_response(encoded_image.tobytes())
        response.headers['Content-Type'] = 'image/png'
        return response
