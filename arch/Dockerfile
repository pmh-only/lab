FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS build
WORKDIR /build/arch
COPY arch/package.json arch/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY arch/build.mjs arch/test.mjs arch/source.json ./
COPY arch/site ./site
COPY docs/architecture/lab-architecture.drawio docs/architecture/lab-architecture-hires.png /build/docs/architecture/
RUN npm run build && npm test

FROM nginxinc/nginx-unprivileged:1.28-alpine@sha256:7377697a821c131a924a7105fafbe7414db4e9fcc77a6f08f776f33f141ec3f8
COPY arch/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /build/arch/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx", "-g", "daemon off;"]
