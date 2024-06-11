FROM alpine as builder-base

WORKDIR /build

RUN apk add --no-cache nodejs npm

RUN npm i -g pnpm

FROM builder-base as builder

COPY source/package.json \
     source/pnpm-lock.json \
     /build/

RUN pnpm i

COPY source/tsconfig.json \
     source/src \
     /build/

RUN pnpm run build

FROM builder-base as dep-resolver

COPY source/package.json \
     source/pnpm-lock.json \
     /build/

RUN pnpm i --omit=dev

FROM alpine as runner

WORKDIR /app

RUN apk add --no-cache nodejs

COPY --from=builder /build/dist /app/dist
COPY --from=dep-resolver /build/node_modules /app/node_modules

CMD ["node", "dist/index.js"]
