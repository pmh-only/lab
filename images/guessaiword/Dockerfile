FROM docker.io/eclipse-temurin:17-jdk-alpine as builder

WORKDIR /build

RUN apk add git

RUN apk add nodejs npm

ARG DISABLE_CACHE

RUN git clone https://github.com/pmh-only/guess-ai-word.git .

WORKDIR /build/backend

RUN ./gradlew bootjar

FROM docker.io/eclipse-temurin:17-jre-alpine as runtime

COPY --from=builder /build/libs/guessaiword-0.0.1-SNAPSHOT.jar /app/app.jar

CMD ["java", "-jar", "/app/app.jar"]
