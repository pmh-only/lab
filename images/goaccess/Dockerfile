# syntax=docker/dockerfile:1
ARG BASE_IMAGE
ARG GEOIP_IMAGE
FROM ${GEOIP_IMAGE} AS geoip
FROM ${BASE_IMAGE}
USER root
COPY --from=geoip /app/GeoLite2-City.mmdb /usr/share/GeoIP/GeoLite2-City.mmdb
COPY --from=geoip /app/GeoLite2-ASN.mmdb /usr/share/GeoIP/GeoLite2-ASN.mmdb
# Parse both datasets using the actual shipped GoAccess before publishing.
RUN printf '1.1.1.1 - - [01/Nov/2026:00:00:00 +0000] "GET / HTTP/1.1" 200 1 "-" "image-build-test"\n' > /tmp/geoip-test.log \
    && goaccess --no-global-config --no-progress --log-format=COMBINED \
       --geoip-database=/usr/share/GeoIP/GeoLite2-City.mmdb \
       --geoip-database=/usr/share/GeoIP/GeoLite2-ASN.mmdb \
       -f /tmp/geoip-test.log -o /tmp/geoip-test.html \
    && rm /tmp/geoip-test.log /tmp/geoip-test.html
