FROM python:3.11-slim

ARG KUBECTL_VERSION=v1.30.5

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && ARCH="$(uname -m)" \
    && case "${ARCH}" in \
      x86_64) K8S_ARCH=amd64 ;; \
      aarch64) K8S_ARCH=arm64 ;; \
      *) echo "unsupported architecture: ${ARCH}" && exit 1 ;; \
    esac \
    && curl -fsSL -o /usr/local/bin/kubectl \
    "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${K8S_ARCH}/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e .
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data/langgraph \
    && chown -R appuser:appuser /data \
    && chmod -R a+rX /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
