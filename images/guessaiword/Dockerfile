FROM docker.io/arm64v8/eclipse-temurin:17-alpine-jre as runtime

WORKDIR /app

USER 1000:1000

COPY app.jar ./app.jar

CMD ["java", "-jar", "./app.jar"]
