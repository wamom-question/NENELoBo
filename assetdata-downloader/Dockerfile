FROM golang:1.25.4-alpine AS builder

WORKDIR /app

# go.mod をコピーして依存関係をダウンロード
COPY go.mod ./
RUN go mod download

# 残りのソースコードをコピー
COPY . .

# バイナリをビルド
RUN CGO_ENABLED=0 GOOS=linux go build -o app .

# 本番イメージを作成
FROM alpine:latest

# アプリケーションのディレクトリを作成
RUN mkdir -p /app/assets

# ビルドしたバイナリをコピー
COPY --from=builder /app/app /app/
COPY --from=builder /app/assets /app/assets

# 環境変数を設定
ENV TZ=Asia/Tokyo

# アプリケーションを指定して実行
CMD ["/app/app"]