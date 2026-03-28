import json
import os
import re
import threading
from collections import Counter

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()
app = Flask(__name__)
is_processing = False

API_URL = os.getenv("SEKAI_UNIQUE_API_URL")
API_KEY = os.getenv("SEKAI_UNIQUE_API_KEY")

BASE_PATH = "/app/assets"
MUSIC_JSON = os.path.join(BASE_PATH, "musics.json")
ARTISTS_JSON = os.path.join(BASE_PATH, "musicArtists.json")
SKIP_JSON = os.path.join(BASE_PATH, "music_skip.json")
OUTPUT_JSON = os.path.join(BASE_PATH, "song_pronunciation.json")


def build_intermediate_data(music_data, artist_data):
    # --- スキップリストの読み込み ---
    skip_ids = set()
    if os.path.exists(SKIP_JSON):
        try:
            with open(SKIP_JSON, "r", encoding="utf-8") as f:
                skip_ids = set(json.load(f))
        except Exception as e:
            print(f"Warning: Failed to load skip list: {e}")

    # アーティスト検索用の辞書
    artists_by_id = {a["id"]: a["pronunciation"] for a in artist_data}
    artists_by_name = {a["name"]: a["pronunciation"] for a in artist_data}

    intermediate_list = []

    for music in music_data:
        # --- スキップ判定 ---
        if music.get("id") in skip_ids:
            continue

        creator_pron = artists_by_id.get(music.get("creatorArtistId"), "")
        lyricist_pron = artists_by_name.get(music.get("lyricist"), "")
        composer_pron = artists_by_name.get(music.get("composer"), "")
        arranger_pron = artists_by_name.get(music.get("arranger"), "")

        obj = {
            "id": music.get("id"),
            "title": music.get("title"),
            "songPronunciation": music.get("pronunciation", ""),
            "creatorArtistPronunciation": creator_pron,
            "lyricistPronunciation": lyricist_pron,
            "composerPronunciation": composer_pron,
            "arrangerPronunciation": arranger_pron,
        }
        intermediate_list.append(obj)

    return intermediate_list


def katakana_to_hiragana(text: str) -> str:
    """カタカナをひらがなに変換する"""
    return "".join(
        [chr(ord(c) - 0x60) if "\u30a1" <= c <= "\u30f6" else c for c in text]
    )


def is_valid_phrase(phrase: str) -> bool:
    """ひらがなとーのみで構成されているか判定"""
    return bool(re.fullmatch(r"[\u3041-\u3096ー]+", phrase))


def generate_phrases(text: str, n: int) -> list[str]:
    """
    1文字ずつスライドしてn文字のハッシュを抽出。
    小書き文字や記号が含まれるものはこの段階で除外する。
    """
    if not text or len(text) < n:
        return []

    # ひらがなに正規化
    text = katakana_to_hiragana(text)

    # 排除対象（小書き文字など）
    unwanted_kana = set("ぁぃぅぇぉゃゅょっ")
    phrases = []

    # モーラ結合をせず、単純に1文字ずつスライド
    for i in range(len(text) - n + 1):
        window = text[i : i + n]

        # 1. 小書き文字が含まれていたらスキップ
        if any(char in unwanted_kana for char in window):
            continue

        # 2. 有効な文字種（ひらがな・ー）以外が含まれていたらスキップ
        if not is_valid_phrase(window):
            continue

        phrases.append(window)

    return phrases


def get_song_all_hashes(song, n):
    """特定の曲の全項目から指定されたn文字のハッシュを抽出"""
    target_keys = [
        "songPronunciation",
        "creatorArtistPronunciation",
        "lyricistPronunciation",
        "composerPronunciation",
        "arrangerPronunciation",
    ]
    raw_hashes = []
    for key in target_keys:
        # split_into_morae を介さず直接呼ぶ
        raw_hashes.extend(generate_phrases(song.get(key, ""), n))

    return list(dict.fromkeys(raw_hashes))


def upload_to_spreadsheet(data):
    # トークンとデータをラップする
    payload = {"token": API_KEY, "payload": data}

    try:
        # タイムアウトを設定してハングアップを防止
        response = requests.post(API_URL, json=payload, timeout=30)
        if response.status_code == 200 and response.text == "Success":
            print("Successfully uploaded to Spreadsheet.")
        else:
            print(f"Upload failed: {response.text} (Status: {response.status_code})")
    except Exception as e:
        print(f"Error during upload: {e}")


def main():
    print(f"--- [Phase 1] Loading JSON files from {BASE_PATH} ---")
    if not os.path.exists(MUSIC_JSON):
        print(f"Error: {MUSIC_JSON} not found.")
        return

    try:
        # ファイルサイズを先にチェックしてログに出す
        m_size = os.path.getsize(MUSIC_JSON) / (1024 * 1024)
        a_size = os.path.getsize(ARTISTS_JSON) / (1024 * 1024)
        print(f"DEBUG: MUSIC_JSON size: {m_size:.2f} MB")
        print(f"DEBUG: ARTISTS_JSON size: {a_size:.2f} MB")

        print("DEBUG: Calling json.load(MUSIC_JSON)...")
        with open(MUSIC_JSON, "r", encoding="utf-8") as f:
            music_data = json.load(f)

        print("DEBUG: Calling json.load(ARTISTS_JSON)...")
        with open(ARTISTS_JSON, "r", encoding="utf-8") as f:
            artist_data = json.load(f)

        print(
            f"Successfully loaded {len(music_data)} musics and {len(artist_data)} artists."
        )
    except Exception as e:
        print(f"Error during JSON loading: {e}")
        return

    print("--- [Phase 2] Building intermediate data (Applying Skip List) ---")
    intermediate_data = build_intermediate_data(music_data, artist_data)
    print(f"Intermediate data built. Total songs to process: {len(intermediate_data)}")

    print("--- [Phase 3] Running hash generation system (n=2 to 6) ---")
    # 進行状況が見えるように、この関数内でログを出すようにします
    final_data = run_hash_generation_system(intermediate_data)
    print(f"Hash generation completed for {len(final_data)} songs.")

    print(f"--- [Phase 4] Writing output to {OUTPUT_JSON} ---")
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

    print("--- [Phase 5] Uploading to Google Spreadsheet ---")
    upload_to_spreadsheet(final_data)


def run_hash_generation_system(intermediate_data):
    # 1. 全楽曲の全可能性を事前に集計
    print("Step 1: Counting all possible phrases across all songs...")
    all_possible_hashes = []
    for i, song in enumerate(intermediate_data):
        for n in [2, 3, 4, 5, 6]:
            hashes = get_song_all_hashes(song, n)
            all_possible_hashes.extend(hashes)
        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1} songs for global count...")

    global_counts = Counter(all_possible_hashes)
    print(f"Global phrase dictionary built. Unique phrases found: {len(global_counts)}")

    # 2. 各楽曲のハッシュ確定処理
    print("Step 2: Determining unique phrases for each song...")
    for i, song in enumerate(intermediate_data):
        found = False
        for n in [2, 3, 4, 5, 6]:
            current_hashes = get_song_all_hashes(song, n)
            unique_phrases = [h for h in current_hashes if global_counts[h] == 1]

            if unique_phrases:
                song["search_phrases"] = unique_phrases
                song["phrases_count"] = n
                found = True
                break

        if not found:
            song["search_phrases"] = [song.get("songPronunciation", "UNKNOWN")]
            song["phrases_count"] = 6

        if (i + 1) % 100 == 0:
            print(f"  Finalized {i + 1} songs...")

    return intermediate_data


@app.route("/update", methods=["POST", "GET"])
def trigger_update():
    global is_processing

    if is_processing:
        return jsonify({"status": "error", "message": "Already processing"}), 429

    thread = threading.Thread(target=run_process)
    thread.start()

    return jsonify({"status": "success", "message": "Update triggered"}), 202


def run_process():
    global is_processing
    is_processing = True
    try:
        print("--- Starting Update Process ---")
        main()
        print("--- Update Process Completed ---")
    except Exception as e:
        print(f"--- Process Failed: {e} ---")
    finally:
        is_processing = False


if __name__ == "__main__":
    threading.Thread(target=run_process).start()
    app.run(host="0.0.0.0", port=53749)
