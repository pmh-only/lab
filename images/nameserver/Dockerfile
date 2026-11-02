# syntax=docker/dockerfile:1
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY images/nameserver/requirements.txt /image-build/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /image-build/requirements.txt \
    && python -c 'import dns.zone; assert dns.__version__ == "2.9.1"'
