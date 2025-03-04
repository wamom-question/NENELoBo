from flask import Flask, jsonify
import requests
import time
import os
import logging

app = Flask(__name__)
LAST_CHECK_FILE = "last_check.txt"
DATA_URL = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/userInformations.json"

# loggingの設定
logging.basicConfig(level=logging.DEBUG)

# 初回起動時は全取得、次回からはlast_checkを利用
def get_last_check_time():
    if os.path.exists(LAST_CHECK_FILE):
        with open(LAST_CHECK_FILE, "r") as f:
            return int(f.read().strip())
    return 0  # 初回のみ全取得

def save_last_check_time(last_check):
    with open(LAST_CHECK_FILE, "w") as f:
        f.write(str(last_check))  # last_check をファイルに保存

@app.route("/announcements", methods=["GET"])
def fetch_announcements():
    last_check = get_last_check_time()
    logging.debug(f"Last check timestamp: {last_check}")  # デバッグ用ログ

    try:
        response = requests.get(DATA_URL)
        response.raise_for_status()
        announcements = response.json()
    except Exception as e:
        return f"エラー: {str(e)}", 500

    new_announcements = []

    if last_check == 0:
        # 初回起動時（過去のお知らせ3つを取得）
        count = 0
        # 逆順でデータを処理（下から取得）
        for item in reversed(announcements):
            logging.debug(f"Checking item with startAt: {item['startAt']}")  # デバッグ用ログ
            # startAt が未来のものは取得しない
            if item["startAt"] <= time.time() * 1000:  # ミリ秒で比較
                if item["browseType"] == "internal":
                    new_announcements.append(item["title"])
                elif item["browseType"] == "external":
                    new_announcements.append(f'[{item["title"]}]({item["path"]})')
                count += 1
            if count >= 3:  # 3つまで取得
                last_check = item["startAt"]  # 最新のお知らせの startAt を保存
                break
        # 初回時にメッセージをDiscordに送信
        if new_announcements:
            new_announcements.insert(0, "過去のお知らせ3つを送信します：")
        save_last_check_time(last_check)  # last_check をファイルに保存
    else:
        # 通常時（last_check 以降の新しいお知らせを取得）
        for item in announcements:
            if item["startAt"] // 1000 >= last_check:  # ミリ秒を秒に変換して比較
                if item["browseType"] == "internal":
                    new_announcements.append(item["title"])
                elif item["browseType"] == "external":
                    new_announcements.append(f'[{item["title"]}]({item["path"]})')

    if new_announcements:
        return "\n".join(new_announcements)
    return "新しいお知らせはありません。"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)