FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir matplotlib
COPY . .
ENV PYTHONUNBUFFERED=1 DIR_LOGS=/app/logs
