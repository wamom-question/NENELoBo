import json
import os
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


def split_into_morae(text: str) -> list[str]:
    """
    文字列をモーラ（音節）単位に分割する。
    小書き文字（ぁぃぅぇぉゃゅょ等）は直前の文字と結合する。
    """
    if not text:
        return []

    # 小書き文字の定義
    small_kana = set("ぁぃぅぇぉゃゅょっァィゥェォャュョ")

    morae = []
    i = 0
    length = len(text)

    while i < length:
        current_char = text[i]

        # 次の文字が存在し、かつそれが小書き文字であれば結合
        if i + 1 < length and text[i + 1] in small_kana:
            morae.append(current_char + text[i + 1])
            i += 2  # 2文字分進む
        else:
            morae.append(current_char)
            i += 1  # 1文字分進む

    return morae


def generate_phrases(morae: list[str], n: int) -> list[str]:
    """
    モーラリストからn-モーラのハッシュ（フレーズ）を抽出する。
    小書き文字を含むフレーズ、または特定の記号を含むフレーズを排除する。
    """
    if len(morae) < n:
        return []

    # 小書き文字の定義（これらが含まれるフレーズは「打ちにくい」として排除）
    # ※ 長音「ー」は通常のフリック1回のためここには含めない
    unwanted_kana = set("ぁぃぅぇぉゃゅょっ")
    del_space = {" ", "　", "・"}
    phrases = []

    # スライディングウィンドウ
    for i in range(len(morae) - n + 1):
        window = morae[i : i + n]
        joined_phrase = "".join(window)

        # 1. フレーズ内に小書き文字が含まれていたらスキップ
        if any(char in unwanted_kana for char in joined_phrase):
            continue
            
        # 2. 空白や区切り文字が含まれていたらスキップ
        if any(s in joined_phrase for s in del_space):
            continue

        phrases.append(joined_phrase)

    return phrases


def process_all_songs_initial_hash(intermediate_data, n=3):
    """
    全楽曲の各項目からハッシュを生成し、全ハッシュのフラットリストを作成する。
    1曲の中で重複するハッシュは事前に統合する。
    """
    all_generated_hashes = []

    target_keys = [
        "songPronunciation",
        "creatorArtistPronunciation",
        "lyricistPronunciation",
        "composerPronunciation",
        "arrangerPronunciation",
    ]

    for song in intermediate_data:
        song_raw_hashes = []
        for key in target_keys:
            text = song.get(key, "")
            if not text:
                continue

            morae = split_into_morae(text)
            phrases = generate_phrases(morae, n)
            song_raw_hashes.extend(phrases)

        # --- 統合処理 (1曲内での重複排除) ---
        # dict.fromkeys() を使うことで、順序を維持したまま重複を消せます
        unique_song_hashes = list(dict.fromkeys(song_raw_hashes))

        song["temp_hashes"] = unique_song_hashes
        # グローバル集計用（このリストには全曲分がフラットに入る）
        all_generated_hashes.extend(unique_song_hashes)

    return all_generated_hashes, intermediate_data


def get_song_all_hashes(song, n):
    """
    特定の曲の全項目から、指定されたnモーラのハッシュを抽出し、
    曲内でユニーク化したリストを返す。
    """
    target_keys = [
        "songPronunciation",
        "creatorArtistPronunciation",
        "lyricistPronunciation",
        "composerPronunciation",
        "arrangerPronunciation",
    ]
    raw_hashes = []
    for key in target_keys:
        morae = split_into_morae(song.get(key, ""))
        raw_hashes.extend(generate_phrases(morae, n))

    # 順序を維持して曲内ユニーク化
    return list(dict.fromkeys(raw_hashes))


def run_hash_generation_system(intermediate_data):
    # 1. 全楽曲の全可能性 (n=3,4,5,6) を事前に集計して重複を厳密にチェック
    all_possible_hashes = []
    for song in intermediate_data:
        for n in [3, 4, 5, 6]:
            hashes = get_song_all_hashes(song, n)
            all_possible_hashes.extend(hashes)

    global_counts = Counter(all_possible_hashes)

    # 2. 各楽曲のハッシュ確定処理
    for song in intermediate_data:
        found = False
        # n=3 から 6 まで順に試行
        for n in [3, 4, 5, 6]:
            current_hashes = get_song_all_hashes(song, n)
            # 世界で自分しか持っていないフレーズを抽出
            unique_phrases = [h for h in current_hashes if global_counts[h] == 1]

            if unique_phrases:
                song["search_phrases"] = unique_phrases
                song["phrases_count"] = n
                found = True
                break

        # 3. 【追加仕様】全滅（n=6までで見つからない）または文字数不足の場合の救済
        if not found:
            song["search_phrases"] = [song["songPronunciation"]]
            song["phrases_count"] = 6  # 探索終了のフラグとしてn=6を保持

    return intermediate_data


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
            
        print(f"Successfully loaded {len(music_data)} musics and {len(artist_data)} artists.")
    except Exception as e:
        print(f"Error during JSON loading: {e}")
        return

    print("--- [Phase 2] Building intermediate data (Applying Skip List) ---")
    intermediate_data = build_intermediate_data(music_data, artist_data)
    print(f"Intermediate data built. Total songs to process: {len(intermediate_data)}")

    print("--- [Phase 3] Running hash generation system (n=3 to 6) ---")
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
        for n in [3, 4, 5, 6]:
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
        for n in [3, 4, 5, 6]:
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
