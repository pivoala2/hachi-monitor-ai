FROM python:3.11-slim

WORKDIR /app

# Pillow用の依存
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Pythonライブラリ
RUN pip install --no-cache-dir \
    google-genai \
    line-bot-sdk \
    flask \
    requests \
    watchdog \
    pillow \
    python-dotenv \
    matplotlib

COPY . /app/
