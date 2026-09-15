FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY services/vectorizer/requirements.txt .
RUN pip install --no-cache-dir --timeout 600 -r requirements.txt

# Copy shared library
COPY shared /app/shared

# Copy service code
COPY services/vectorizer/src /app/src

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]
