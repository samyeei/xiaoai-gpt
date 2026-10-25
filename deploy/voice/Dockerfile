FROM python:3.12-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY deploy/voice/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY deploy/voice /app
COPY config /config
ENV PYTHONUNBUFFERED=1 MODELS_DIR=/models
CMD ["python", "worker.py"]
