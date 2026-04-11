FROM node:20-alpine

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG INTERNAL_API_URL=http://control-api:8000
ARG NEXT_PUBLIC_APP_PHASE=P0

ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV INTERNAL_API_URL=${INTERNAL_API_URL}
ENV NEXT_PUBLIC_APP_PHASE=${NEXT_PUBLIC_APP_PHASE}

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY app ./app
COPY public ./public
COPY next.config.mjs tsconfig.json next-env.d.ts ./

RUN npm run build \
 && cp -r .next/static .next/standalone/.next/static \
 && cp -r public .next/standalone/public

EXPOSE 3000

CMD ["node", ".next/standalone/server.js"]
