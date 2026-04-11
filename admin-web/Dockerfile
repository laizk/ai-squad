FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY app ./app
COPY public ./public
COPY next.config.mjs tsconfig.json next-env.d.ts ./

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
