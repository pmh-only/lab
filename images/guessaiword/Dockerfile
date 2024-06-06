FROM alpine as builder

WORKDIR /build

RUN apk add git nodejs npm openjdk17-jdk

ARG DISABLE_CACHE

RUN git clone https://github.com/pmh-only/guess-ai-word.git .

WORKDIR /build/backend

RUN ./gradlew bootjar

FROM builder as runtime

RUN apk add --no-cache openjdk17-jre

COPY --from=builder /build/libs/guessaiword-0.0.1-SNAPSHOT.jar /app/app.jar

CMD ["java", "-jar", "/app/app.jar"]
