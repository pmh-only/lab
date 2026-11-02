# syntax=docker/dockerfile:1
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG PYTHON_REQUIREMENTS
RUN mkdir /image-build \
    && python -c 'import json, os, pathlib; pathlib.Path("/image-build/requirements.txt").write_text("\n".join(json.loads(os.environ["PYTHON_REQUIREMENTS"])))' \
    && pip install --no-cache-dir --only-binary=:all: --require-hashes -r /image-build/requirements.txt \
    && python -c 'import dns.zone'
