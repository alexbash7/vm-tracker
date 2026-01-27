FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Pillow
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY hash-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hash-worker/worker.py .

CMD ["python", "-u", "worker.py"]
