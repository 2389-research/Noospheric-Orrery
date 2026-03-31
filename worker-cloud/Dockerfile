FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install simmer-sdk from local path
COPY simmer-sdk/ /tmp/simmer-sdk/
RUN pip install --no-cache-dir /tmp/simmer-sdk/ && rm -rf /tmp/simmer-sdk/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ worker/

# Cloud Run Job: runs once and exits
CMD ["python", "-m", "worker.main"]
