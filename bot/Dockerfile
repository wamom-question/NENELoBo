FROM node:18-slim

WORKDIR /usr/src/app

RUN apt-get update && apt-get install -y build-essential python3

COPY package*.json ./
RUN npm install
# NOTE: better-sqlite3 is not required by the bot source in this repo.
# Installing native modules can cause malloc/native crashes in some envs
# (architecture mismatch / incompatible prebuilt binary). Omit the
# separate install here; add build-time deps and rebuild from source only
# if you actually need better-sqlite3.

COPY . .

CMD ["node", "bot.js"]