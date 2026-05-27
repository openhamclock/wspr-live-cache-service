FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY wspr_live_cache /app/wspr_live_cache
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8081
CMD ["python", "-m", "wspr_live_cache"]
