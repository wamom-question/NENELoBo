FROM python:3.9-slim

# 1. OSパッケージのインストール (tesseract-ocrと依存ライブラリ)
# tesseract-ocr 本体と、実行に必要な依存ライブラリをインストールします。
# slim イメージで apt-get を実行する際は、常に update/cleanup をセットで行い、
# --no-install-recommends を使用して不要なパッケージを削減します。
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libtesseract5 \
        # tesseractが依存する可能性のある主要なライブラリ (状況に応じて調整)
        libleptonica-dev \
        # numpy/torchがビルドを必要とする場合（通常は不要だが、エラーが出る場合のみ追加）
        # build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY requirements.txt .

# 2. Python依存関係のインストール
# pip install はキャッシュを使用しない設定(--no-cache-dir)で行い、
# numpy/torchのバージョンを固定してインストールします。
# numpyとtorchは通常、ビルド済みホイールが提供されているため、build-essentialは多くの場合不要です。
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    torch==2.1.2 torchvision==0.16.2 \
    -r requirements.txt

# 3. アプリケーションコードのコピー
COPY . .

# 環境変数とCMDは元の設定を維持
ENV GUNICORN_WORKERS=2
# ... (その他ENV)
CMD ["gunicorn", "-b", "0.0.0.0:53744", "--config", "./gunicorn_conf.py", "result_calc:app"]