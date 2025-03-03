# ベースイメージとしてNode.jsを使用
FROM node:18

# 作業ディレクトリを作成
WORKDIR /usr/src/app

# package.json と package-lock.json をコピー
COPY package*.json ./

# 依存関係をインストール
RUN npm install

# アプリケーションのコードをコピー
COPY . .

# コンテナ起動時に実行するコマンド
CMD ["node", "bot.js"]