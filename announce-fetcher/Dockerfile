# --- Build stage ---
FROM golang:1.25.4 AS builder

WORKDIR /app

COPY go.mod ./
RUN go mod download

# アプリ本体をコピー
COPY . .

# バイナリ作成（静的リンク）
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o app .

# --- Runtime stage ---
FROM scratch

WORKDIR /app

# ビルドしたバイナリをコピー
COPY --from=builder /app/app /app/app

# チェックファイル保存用に writable な作業ディレクトリ
COPY --from=builder /app/last_check.txt /app/last_check.txt

EXPOSE 5000

ENTRYPOINT ["/app/app"]