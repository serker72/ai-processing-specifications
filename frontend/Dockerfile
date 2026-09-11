# Node должен совпадать с .nvmrc (локальная разработка): разные минорные версии
# дают разный сборочный вывод, а nuxt требует node >=20.19.0 или >=22.12.0.
FROM node:24-alpine

WORKDIR /app

# Lock-файл обязателен: без него npm разрешает версии заново и образ
# расходится с локальной сборкой.
COPY package.json package-lock.json ./

RUN npm ci --legacy-peer-deps

COPY . .

RUN npm run build

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]
