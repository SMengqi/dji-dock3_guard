# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 依赖声明先装,利用 layer cache
COPY pyproject.toml README.md ./
COPY src/dock_guard/__init__.py ./src/dock_guard/__init__.py
RUN pip install --upgrade pip && pip install -e .

# 完整源码
COPY src/ ./src/
COPY config/ ./config/

RUN mkdir -p /app/data

EXPOSE 8080

ENTRYPOINT ["python", "-m", "dock_guard"]
