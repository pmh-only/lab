FROM alpine as build

WORKDIR /build

RUN apk add git nodejs npm openjdk17-jdk

COPY /source/frontend/ /build/frontend/

WORKDIR /build/frontend/

RUN npm i

RUN npm run build

COPY /source/backend/ /build/backend/

WORKDIR /build/backend

RUN echo "#!/bin/sh" > scripts/runFrontendScript.sh

RUN rm src/main/resources/frontend && mkdir -p src/main/resources/frontend

RUN cp /build/frontend/dist src/main/resources/frontend/dist

RUN ./gradlew bootjar

FROM build as runtime

RUN apk add --no-cache openjdk17-jre

USER 1000:1000

WORKDIR /app

COPY --from=build /build/libs/guessaiword-0.0.1-SNAPSHOT.jar /app/app.jar

CMD ["java", "-jar", "./app.jar"]
