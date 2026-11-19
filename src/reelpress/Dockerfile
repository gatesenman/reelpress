FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REELPRESS_DATA_DIR=/data \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-wqy-microhei \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[upload]" \
    && playwright install --with-deps chromium

COPY config.example.toml .env.example ./
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8765

CMD ["python", "-m", "reelpress", "serve", "--host", "0.0.0.0", "--port", "8765"]
