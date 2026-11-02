# syntax=docker/dockerfile:1
ARG BASE_IMAGE
FROM ${BASE_IMAGE} AS prepare
USER root
COPY seafile/prepare_mysql_plugins.py /image-build/prepare_mysql_plugins.py
COPY images/seafile/prepare-installer.py /image-build/prepare-installer.py
RUN mkdir -p /run/mariadb-client-plugins \
    && python3 /image-build/prepare_mysql_plugins.py \
    && python3 /image-build/prepare-installer.py

FROM ${BASE_IMAGE}
COPY --from=prepare /run/mariadb-client-plugins/ /opt/lab/mysql-plugins/
COPY --from=prepare /opt/lab/installer/ /opt/
ENV MARIADB_PLUGIN_DIR=/opt/lab/mysql-plugins
