FROM golang:1.25.4-alpine AS builder

WORKDIR /app

# go.mod をコピーして依存関係をダウンロード
COPY go.mod ./
RUN go mod download

# アプリケーションのソースコードをコピー
COPY . .

# Goアプリケーションをビルド
RUN go build -o downloader .

# 実行ステージ
FROM alpine:latest
WORKDIR /app

# 必要なライブラリをインストール
RUN apk add --no-cache ca-certificates

# ビルドされたアプリケーションをコピー
COPY --from=builder /app/downloader .

# 実行コマンドを指定
CMD ["./downloader"]