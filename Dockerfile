FROM python:3.7-alpine3.14

RUN apk add --no-cache git build-base linux-headers && \
    pip install pipenv

RUN adduser -D user
RUN mkdir -p /usr/src/app && chown user:user /usr/src/app
WORKDIR /usr/src/app
USER user

COPY Pipfile* ./
RUN  pipenv install --deploy --ignore-pipfile

COPY . .

CMD ["pipenv", "run", "python", "app.py"]