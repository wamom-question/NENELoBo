FROM golang:1.25.4-alpine AS builder

WORKDIR /app

# go.mod をコピーして依存関係をダウンロード
COPY go.mod ./
RUN go mod download

# 必要なライブラリをインストール
RUN apk add --no-cache bash

# Goのアプリケーションを追加
COPY . .

# Goアプリケーションをビルド
RUN go build -o /app/downloader .

# 実行ステージ
FROM alpine:latest
WORKDIR /root/

# ビルドしたアプリケーションをコピー
COPY --from=builder /app/downloader .

# アプリケーションを実行
CMD ["./downloader"] 