# より軽量なPythonイメージを使用
FROM python:3.9-slim

# OSパッケージのインストール (tesseract-ocr)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

# アプリケーションの作業ディレクトリを設定
WORKDIR /usr/src/app

# 依存関係のインストール (ビルドキャッシュの最適化のため、requirements.txtを先にコピー)
COPY requirements.txt requirements.txt

# numpyとtorchのバージョンを固定してインストール (torchの依存関係解決を助けるため)
RUN pip install numpy==1.26.4
RUN pip install --no-cache-dir torch==2.1.2 torchvision==0.16.2

# その他の依存関係をインストール
# easyocrはこのステップに含まれているはず
RUN pip install --no-cache-dir -r requirements.txt

# --- EasyOCRモデルの事前ダウンロード ---
# /root/.EasyOCR/model にモデルがキャッシュされる
# このステップは requirements.txt が変更されない限り、キャッシュが効く
RUN python -c "import easyocr; easyocr.Reader(['en', 'ja'], gpu=False)"

# アプリケーションコードをコピー
COPY . .

# Default environment variables (can be overridden at runtime)
ENV GUNICORN_WORKERS=2
ENV GUNICORN_THREADS=4
ENV GUNICORN_TIMEOUT=120

# Run with gunicorn in production-style mode, reading `app` from result_calc.py
# gunicornの設定ファイルを参照し、result_calcモジュールからappオブジェクトを実行
# 以前のログで 'result_calc' モジュールが見つからない警告があったため、
# Gunicornが実行されるこのディレクトリに result_calc.py が存在することを確認してください。
CMD ["gunicorn", "-b", "0.0.0.0:53744", "--config", "./gunicorn_conf.py", "result-calc:app"]