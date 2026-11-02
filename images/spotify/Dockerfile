# syntax=docker/dockerfile:1
ARG BASE_IMAGE
FROM ${BASE_IMAGE} AS prepare
USER root
COPY spotify/prepare-api.mjs /image-build/prepare.mjs
RUN mkdir /prepared && node /image-build/prepare.mjs \
    && node --check /prepared/index.js

FROM ${BASE_IMAGE}
COPY --from=prepare /prepared/index.js /app/apps/server/build/index.js
