# syntax=docker/dockerfile:1
ARG BASE_IMAGE
FROM ${BASE_IMAGE} AS prepare
USER root
COPY trace/prepare-clickhouse-client.mjs /image-build/prepare.mjs
RUN mkdir /prepared && node /image-build/prepare.mjs \
    && node --check /prepared/client.js

FROM ${BASE_IMAGE}
COPY --from=prepare /prepared/client.js /app/dist/db/clickhouse/client.js
