FROM alpine as builder-base

WORKDIR /build

RUN apk add --no-cache nodejs npm

RUN npm i -g pnpm

FROM builder-base as builder

COPY source/package.json \
     source/pnpm-lock.yaml \
     /build/

RUN pnpm i

COPY source/tsconfig.json /build/
COPY source/src/ /build/src/

RUN pnpm run build

FROM builder-base as dep-resolver

COPY source/package.json \
     source/pnpm-lock.yaml \
     /build/

RUN pnpm i -P

FROM alpine as runner

WORKDIR /app

RUN apk add --no-cache nodejs

COPY --from=builder /build/dist /app/dist
COPY --from=dep-resolver /build/node_modules /app/node_modules

CMD ["node", "dist/main.js"]
