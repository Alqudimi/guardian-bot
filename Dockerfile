FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies required by async PostgreSQL clients and native wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN mkdir -p /app/model_cache \
    && useradd --create-home --uid 1000 botuser \
    && chown -R botuser:botuser /app

USER botuser

CMD ["python", "main.py"]
