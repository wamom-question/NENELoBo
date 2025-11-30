# --- Stage 1: builder ---
FROM python:3.9 as builder

# 1. OSパッケージのインストール (tesseract-ocrとビルドに必要なツール)
# tesseract-ocr は実行時にも必要なのでそのままインストール
# ただし、torchのインストールにビルドツール（gcc/g++など）が必要な場合、ここで追加
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        # ↓ torch/numpyのビルドが必要な場合にのみ追加（多くの場合不要だが念のため）
        # build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# 2. 依存関係のインストール (torchを含め、すべてのpip依存関係をここで完結させる)
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    torch==2.1.2 torchvision==0.16.2 \
    -r requirements.txt
# --- Stage 2: final ---
FROM python:3.9-slim

# 1. builderからOSパッケージの環境をコピー (tesseract-ocrのライブラリ)
# tesseract-ocrと依存ライブラリを実行環境にコピーするために必要
RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*
    
WORKDIR /usr/src/app

# 2. builderステージからPythonライブラリをコピー
# site-packages フォルダ全体をコピーします
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages

# 3. builderステージからEasyOCRモデルをコピー
# モデルは /root/.EasyOCR/model にあるため、環境変数を考慮して/usr/src/app/.EasyOCR/model などにコピーするのが安全です。
# ただし、ユーザーがrootである場合、/root/.EasyOCR/model のままコピーできます。
COPY --from=builder /root/.EasyOCR/model /root/.EasyOCR/model

# 4. アプリケーションコードをコピー
COPY . .

# 環境変数とCMDは元の設定を維持
ENV GUNICORN_WORKERS=2
# ... (その他ENV)
CMD ["gunicorn", "-b", "0.0.0.0:53744", "--config", "./gunicorn_conf.py", "result_calc:app"]