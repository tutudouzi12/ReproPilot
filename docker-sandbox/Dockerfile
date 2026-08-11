FROM python:3.11-slim

ARG TORCH_VERSION=2.13.0

WORKDIR /app
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch==${TORCH_VERSION}+cpu"
COPY pyproject.toml ./
COPY app ./app
COPY run.py ./
RUN pip install --no-cache-dir .

EXPOSE 8082
CMD ["python", "run.py"]
