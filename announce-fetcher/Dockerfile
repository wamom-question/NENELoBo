# --- Build stage ---
FROM golang:1.25.4-alpine AS builder

WORKDIR /app

COPY go.mod ./
RUN go mod download

# アプリ本体をコピー
COPY . .

# バイナリ作成（静的リンク）
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o app .

# チェックファイルを生成
RUN mkdir -p /app/data
RUN touch /app/data/last_check.txt  # このファイルを生成

# --- Runtime stage ---
FROM alpine:latest

WORKDIR /app

# ビルドしたバイナリをコピー
COPY --from=builder /app/app /app/app

# チェックファイルをコピー
COPY --from=builder /app/data/last_check.txt /app/data/last_check.txt

EXPOSE 5000

ENTRYPOINT ["/app/app"]
