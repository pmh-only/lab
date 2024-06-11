FROM ubuntu as build

RUN apt-get update && \
    apt-get install -y curl gnupg
RUN curl -sL https://deb.nodesource.com/setup_20.x  | bash -
RUN apt-get -y install openjdk-17-jdk nodejs

WORKDIR /build/frontend/

COPY source/frontend/package.json \
     /build/frontend/

RUN npm i

COPY source/frontend/* /build/frontend/
COPY source/frontend/src /build/frontend/src
COPY source/frontend/public /build/frontend/public

RUN npm run build

WORKDIR /build/backend

COPY source/backend/ /build/backend/

RUN echo "#!/bin/sh" > scripts/runFrontendScript.sh && \
    rm src/main/resources/frontend && \
    mkdir -p src/main/resources/frontend && \
    cp -r /build/frontend/dist src/main/resources/frontend/dist

RUN ./gradlew bootjar

FROM alpine as runtime

RUN apk add --no-cache openjdk17-jre

USER 1000:1000

WORKDIR /app

COPY --from=build /build/backend/output/libs/guessaiword-0.0.1-SNAPSHOT.jar /app/app.jar

CMD ["java", "-jar", "./app.jar"]
