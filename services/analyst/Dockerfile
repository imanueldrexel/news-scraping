FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY services/analyst/requirements.txt .
RUN pip install --no-cache-dir --timeout 600 -r requirements.txt

COPY shared /app/shared
COPY services/analyst/src /app/src

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]
