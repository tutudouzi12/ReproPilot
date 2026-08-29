FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241

ARG DEBIAN_FRONTEND=noninteractive
ARG SOURCE_REVISION

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates g++ make python3 \
    && rm -rf /var/lib/apt/lists/*

COPY fastText /src/fastText
COPY SOURCE_REVISION /opt/repropilot/SOURCE_REVISION

RUN test "$(cat /opt/repropilot/SOURCE_REVISION)" = "$SOURCE_REVISION" \
    && make -C /src/fastText -j2 \
    && install -m 0755 /src/fastText/fasttext /usr/local/bin/fasttext \
    && rm -rf /src/fastText

COPY container_runner.py /opt/repropilot/container_runner.py

ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python3", "/opt/repropilot/container_runner.py"]
