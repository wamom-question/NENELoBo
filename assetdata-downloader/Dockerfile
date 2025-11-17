FROM golang:1.25.4-alpine AS builder

WORKDIR /app

# go.mod をコピーして依存関係をダウンロード
COPY go.mod ./
RUN go mod download

# 必要なライブラリをインストール
RUN apk add --no-cache bash dcron

# Goのアプリケーションを追加
COPY . .

# Goアプリケーションをビルド
RUN go build -o downloader .

# 実行ステージ
FROM alpine:latest
WORKDIR /root/

# ビルドしたアプリケーションをコピー
COPY --from=builder /app/downloader .

# crontabを設定
COPY crontab /etc/crontabs/root

# Cronを実行
CMD ["crond", "-f"]


