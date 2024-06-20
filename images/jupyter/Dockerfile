FROM jupyter/minimal-notebook

USER root

RUN apt update -y && apt install -y build-essential

RUN curl -fsSL https://raw.githubusercontent.com/tj/n/master/bin/n | bash -s lts

RUN npm i -g tslab

RUN tslab install

USER $NB_USER
