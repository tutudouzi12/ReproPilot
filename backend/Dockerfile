FROM python:3.11-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY app ./app
COPY run.py ./
RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["python", "run.py"]
