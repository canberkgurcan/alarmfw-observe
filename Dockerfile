# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.29.0" \
    "pyyaml>=6.0" \
    "requests>=2.31.0"

COPY . .

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
