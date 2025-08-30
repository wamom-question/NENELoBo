FROM node:18-slim

WORKDIR /usr/src/app

RUN apt-get update && apt-get install -y build-essential python3

COPY package*.json ./
RUN npm install
RUN npm install better-sqlite3

COPY . .

CMD ["node", "bot.js"]