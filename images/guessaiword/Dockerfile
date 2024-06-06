FROM alpine as runtime

RUN apk add --no-cache openjdk17-jre

USER 1000:1000

WORKDIR /app

COPY ./app.jar /app/app.jar

CMD ["java", "-jar", "./app.jar"]
