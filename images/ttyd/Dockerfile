FROM tsl0922/ttyd:alpine

RUN apk add --no-cache openssh

COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

CMD ["ttyd", "-W", "/entrypoint.sh"]
