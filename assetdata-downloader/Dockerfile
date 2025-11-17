FROM golang:alpine

WORKDIR /app

COPY go.mod ./
RUN go mod download

# 必要なライブラリをインストール
RUN apk add --no-cache bash dcron

# Goのアプリケーションを追加
COPY . .

# Goアプリケーションをビルド
RUN go build -o downloader .

# crontabを設定
COPY crontab /etc/crontabs/root

# Cronを実行
CMD ["crond", "-f"]

