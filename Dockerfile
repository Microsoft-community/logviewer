FROM python:3.14-slim

RUN pip install --no-cache-dir pipenv

RUN useradd --create-home user
RUN mkdir -p /usr/src/app && chown user:user /usr/src/app
WORKDIR /usr/src/app
USER user

COPY Pipfile* ./
RUN  pipenv install --deploy --ignore-pipfile

COPY . .

CMD ["pipenv", "run", "python", "app.py"]