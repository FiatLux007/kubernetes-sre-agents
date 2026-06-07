FROM alpine:3.20

ARG KUBECTL_VERSION=v1.30.5
ARG HELM_VERSION=v3.16.4

RUN apk add --no-cache bash ca-certificates curl openssl tar gzip

RUN ARCH="$(uname -m)" \
    && case "${ARCH}" in \
      x86_64) K8S_ARCH=amd64 ;; \
      aarch64) K8S_ARCH=arm64 ;; \
      *) echo "unsupported architecture: ${ARCH}" && exit 1 ;; \
    esac \
    && curl -fsSL -o /usr/local/bin/kubectl \
    "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${K8S_ARCH}/kubectl" \
    && chmod +x /usr/local/bin/kubectl

RUN ARCH="$(uname -m)" \
    && case "${ARCH}" in \
      x86_64) HELM_ARCH=amd64 ;; \
      aarch64) HELM_ARCH=arm64 ;; \
      *) echo "unsupported architecture: ${ARCH}" && exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/helm.tar.gz \
    "https://get.helm.sh/helm-${HELM_VERSION}-linux-${HELM_ARCH}.tar.gz" \
    && tar -xzf /tmp/helm.tar.gz -C /tmp \
    && mv "/tmp/linux-${HELM_ARCH}/helm" /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm

WORKDIR /workspace

COPY bootstrap/bootstrap.sh /usr/local/bin/k8s-agent-bootstrap
RUN chmod +x /usr/local/bin/k8s-agent-bootstrap

CMD ["k8s-agent-bootstrap"]
