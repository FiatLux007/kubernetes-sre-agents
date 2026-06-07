#!/usr/bin/env bash
set -euo pipefail

KUBECONFIG_PATH="${KUBECONFIG_PATH:-/kubeconfig/kubeconfig.yaml}"
NAMESPACE="${DEMO_NAMESPACE:-k8s-agent-demo}"
ROBUSTA_VALUES_TEMPLATE="${ROBUSTA_VALUES_TEMPLATE:-/workspace/deploy/robusta/values.template.yaml}"
ROBUSTA_VALUES_GENERATED="${ROBUSTA_VALUES_GENERATED:-/tmp/robusta-values.yaml}"
if [[ "${WEBHOOK_URL:-}" == *"k8s-agent-api"* ]]; then
  API_IP=$(getent hosts k8s-agent-api | awk '{ print $1 }' || ping -c 1 k8s-agent-api | head -1 | awk -F'[()]' '{print $2}')
  WEBHOOK_URL="http://${API_IP}:8000/webhooks/robusta"
else
  WEBHOOK_URL="${WEBHOOK_URL:-http://k8s-agent-api:8000/webhooks/robusta}"
fi

export KUBECONFIG="${KUBECONFIG_PATH}"

wait_for_file() {
  local path="$1"
  for _ in $(seq 1 120); do
    if [ -s "$path" ]; then
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for file: $path"
  exit 1
}

normalize_kubeconfig() {
  sed -i 's|https://127.0.0.1:6443|https://k3s:6443|g' "${KUBECONFIG_PATH}"
  kubectl config set-cluster default \
    --server=https://k3s:6443 \
    --insecure-skip-tls-verify=true >/dev/null
}

wait_for_k8s() {
  normalize_kubeconfig
  for _ in $(seq 1 120); do
    if kubectl get nodes >/dev/null 2>&1; then
      if kubectl get node k3s-demo >/dev/null 2>&1; then
        kubectl wait --for=condition=Ready node/k3s-demo --timeout=120s
      else
        kubectl wait --for=condition=Ready node --all --timeout=120s
      fi
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for k3s API"
  exit 1
}

wait_for_agent() {
  for _ in $(seq 1 120); do
    if curl -fsS "http://k8s-agent-api:8000/readyz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for K8s-Agent API"
  exit 1
}

install_robusta() {
  sed "s|__WEBHOOK_URL__|${WEBHOOK_URL}|g" "${ROBUSTA_VALUES_TEMPLATE}" > "${ROBUSTA_VALUES_GENERATED}"
  helm repo add robusta https://robusta-charts.storage.googleapis.com >/dev/null
  helm repo update >/dev/null
  helm upgrade --install robusta robusta/robusta \
    --namespace robusta \
    --create-namespace \
    --values "${ROBUSTA_VALUES_GENERATED}"
}

install_argocd() {
  kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply --server-side --force-conflicts -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
  
  echo "Waiting for ArgoCD deployments..."
  for _ in $(seq 1 60); do
    if kubectl get deployment -n argocd argocd-server >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  kubectl wait --for=condition=Available deployment/argocd-server -n argocd --timeout=300s
  
  echo "Applying ArgoCD GitOps Application..."
  sed "s|__GITOPS_REPO_URL__|${GITOPS_REPO_URL}|g" /workspace/deploy/argocd-app.template.yaml > /tmp/argocd-app.yaml
  kubectl apply -f /tmp/argocd-app.yaml
}

main() {
  case "${1:-}" in
    status)
      wait_for_file "${KUBECONFIG_PATH}"
      wait_for_k8s
      kubectl get nodes
      kubectl get pods -A
      kubectl get pods -n "${NAMESPACE}" || true
      return 0
      ;;
    trigger)
      wait_for_file "${KUBECONFIG_PATH}"
      wait_for_k8s
      case "${2:-}" in
        oom)
          kubectl rollout restart deployment/oom-demo -n "${NAMESPACE}"
          ;;
        crashloop)
          kubectl rollout restart deployment/crashloop-demo -n "${NAMESPACE}"
          ;;
        *)
          echo "Usage: k8s-agent-bootstrap trigger oom|crashloop"
          exit 1
          ;;
      esac
      return 0
      ;;
    kubectl)
      wait_for_file "${KUBECONFIG_PATH}"
      normalize_kubeconfig
      shift
      kubectl "$@"
      return 0
      ;;
  esac

  wait_for_file "${KUBECONFIG_PATH}"
  wait_for_k8s
  wait_for_agent
  install_robusta
  install_argocd
  echo "K8s-Agent compose demo bootstrap completed."
}

main "$@"
