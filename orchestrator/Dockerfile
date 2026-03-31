FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY src/ src/
EXPOSE 8080
# Cloud Run uses PORT env var (defaults to 8080)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
