from flask import Flask, jsonify
import requests
import time
import os
import logging

app = Flask(__name__)
LAST_CHECK_FILE = "last_check.txt"
DATA_URL = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/userInformations.json"

# loggingの設定
logging.basicConfig(level=logging.INFO)  # ログレベルをINFOにして冗長なログを減らす

# 前回のチェック時刻を取得
def get_last_check_time():
    if os.path.exists(LAST_CHECK_FILE):
        with open(LAST_CHECK_FILE, "r") as f:
            return int(f.read().strip())
    
    # 初回実行時は現在の時刻を保存して、通知は送らない
    current_time = int(time.time())
    save_last_check_time(current_time)
    return current_time  

# 現在のチェック時刻を保存
def save_last_check_time(timestamp):
    with open(LAST_CHECK_FILE, "w") as f:
        f.write(str(timestamp))

@app.route("/announcements", methods=["GET"])
def fetch_announcements():
    last_check = get_last_check_time()
    current_time = int(time.time())  # 現在のUNIX時刻
    logging.info(f"Checking announcements from {last_check} to {current_time}")

    try:
        response = requests.get(DATA_URL)
        response.raise_for_status()
        announcements = response.json()
    except Exception as e:
        logging.error(f"API Fetch Error: {e}")
        return f"エラー: {str(e)}", 500

    new_announcements = []

    for item in announcements:
        start_at_seconds = item["startAt"] // 1000  # ミリ秒を秒に変換
        if last_check <= start_at_seconds <= current_time:  # last_check から現在の時刻の範囲のみ
            if item["browseType"] == "internal":
                new_announcements.append(item["title"])
            elif item["browseType"] == "external":
                new_announcements.append(f'[{item["title"]}]({item["path"]})')

    if new_announcements:
        save_last_check_time(current_time)  # 通知があった場合のみ更新
        return "\n".join(new_announcements)
    
    return "新しいお知らせはありません。"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)