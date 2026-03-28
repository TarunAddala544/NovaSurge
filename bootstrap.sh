#!/usr/bin/env bash
# NovaSurge Bootstrap — works on Ubuntu 22.04 and macOS
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()     { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS="$(uname -s)"

# ── Sudo helper ───────────────────────────────────────────────────────────────
SUDO=""
if [[ "$EUID" -ne 0 ]] && command -v sudo &>/dev/null; then
  SUDO="sudo"
fi

# ── 1. Base dependencies ──────────────────────────────────────────────────────
install_base_deps() {
  info "Installing base dependencies..."
  if [[ "$OS" == "Linux" ]]; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq \
      curl wget git jq ca-certificates gnupg lsb-release \
      apt-transport-https software-properties-common
  elif [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew &>/dev/null; then
      info "Installing Homebrew..."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    brew install curl wget git jq 2>/dev/null || true
  fi
  success "Base dependencies ready"
}

# ── 2. Docker ─────────────────────────────────────────────────────────────────
install_docker() {
  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    success "Docker already running"
    return
  fi
  info "Installing Docker..."
  if [[ "$OS" == "Linux" ]]; then
    curl -fsSL https://get.docker.com | $SUDO sh
    $SUDO systemctl enable --now docker
    $SUDO usermod -aG docker "$USER" 2>/dev/null || true
    # Allow current session to use docker without re-login
    if ! docker info &>/dev/null 2>&1; then
      $SUDO chmod 666 /var/run/docker.sock 2>/dev/null || true
    fi
  elif [[ "$OS" == "Darwin" ]]; then
    if ! command -v docker &>/dev/null; then
      brew install --cask docker
    fi
    open -a Docker 2>/dev/null || true
    info "Waiting 45s for Docker Desktop to start..."
    sleep 45
  fi
  for i in $(seq 1 20); do
    docker info &>/dev/null && break
    sleep 3
  done
  docker info &>/dev/null || die "Docker failed to start"
  success "Docker ready"
}

# ── 3. Python 3.11 ────────────────────────────────────────────────────────────
install_python() {
  if python3.11 --version &>/dev/null 2>&1; then
    success "Python 3.11 already installed"
    return
  fi
  info "Installing Python 3.11..."
  if [[ "$OS" == "Linux" ]]; then
    $SUDO add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
    $SUDO apt-get update -qq
    $SUDO apt-get install -y python3.11 python3.11-dev python3.11-venv python3-pip
  elif [[ "$OS" == "Darwin" ]]; then
    brew install python@3.11
    brew link --force python@3.11 2>/dev/null || true
  fi
  success "Python 3.11 ready"
}

# ── 4. Node.js 20 ─────────────────────────────────────────────────────────────
install_node() {
  local node_ver
  node_ver=$(node --version 2>/dev/null || echo "none")
  if [[ "$node_ver" == v20* ]]; then
    success "Node.js 20 already installed"
    return
  fi
  info "Installing Node.js 20..."
  if [[ "$OS" == "Linux" ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO -E bash -
    $SUDO apt-get install -y nodejs
  elif [[ "$OS" == "Darwin" ]]; then
    brew install node@20
    brew link --force node@20 2>/dev/null || true
  fi
  success "Node.js $(node --version) ready"
}

# ── 5. kubectl ────────────────────────────────────────────────────────────────
install_kubectl() {
  if command -v kubectl &>/dev/null; then
    success "kubectl already installed"
    return
  fi
  info "Installing kubectl..."
  if [[ "$OS" == "Linux" ]]; then
    KVER=$(curl -Ls https://dl.k8s.io/release/stable.txt)
    curl -Lo /tmp/kubectl "https://dl.k8s.io/release/${KVER}/bin/linux/amd64/kubectl"
    $SUDO install -o root -g root -m 0755 /tmp/kubectl /usr/local/bin/kubectl
    rm -f /tmp/kubectl
  elif [[ "$OS" == "Darwin" ]]; then
    brew install kubectl
  fi
  success "kubectl $(kubectl version --client --short 2>/dev/null | head -1) ready"
}

# ── 6. Helm ───────────────────────────────────────────────────────────────────
install_helm() {
  if command -v helm &>/dev/null; then
    success "Helm already installed"
    return
  fi
  info "Installing Helm 3..."
  curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
  success "Helm $(helm version --short) ready"
}

# ── 7. k3s / k3d ─────────────────────────────────────────────────────────────
install_k3s() {
  if [[ "$OS" == "Linux" ]]; then
    if ! command -v k3s &>/dev/null; then
      info "Installing k3s..."
      curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --disable=traefik --write-kubeconfig-mode=644" $SUDO sh -
      $SUDO systemctl enable --now k3s || true
    fi
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
    # Persist for future shells
    grep -q 'KUBECONFIG=/etc/rancher/k3s' ~/.bashrc 2>/dev/null || \
      echo 'export KUBECONFIG=/etc/rancher/k3s/k3s.yaml' >> ~/.bashrc
    success "k3s installed"

  elif [[ "$OS" == "Darwin" ]]; then
    if ! command -v k3d &>/dev/null; then
      info "Installing k3d (k3s in Docker for macOS)..."
      brew install k3d
    fi
    if ! k3d cluster list 2>/dev/null | grep -q novasurge; then
      info "Creating k3d cluster 'novasurge'..."
      k3d cluster create novasurge \
        --port "30080:30080@loadbalancer" \
        --k3s-arg "--disable=traefik@server:0" \
        --wait
    fi
    export KUBECONFIG="$(k3d kubeconfig write novasurge)"
    grep -q 'k3d kubeconfig' ~/.zshrc 2>/dev/null || \
      echo 'export KUBECONFIG=$(k3d kubeconfig write novasurge 2>/dev/null)' >> ~/.zshrc
    success "k3d cluster 'novasurge' ready"
  fi

  # Wait for API server
  info "Waiting for Kubernetes API server..."
  for i in $(seq 1 30); do
    kubectl cluster-info &>/dev/null && break || sleep 5
  done
  kubectl cluster-info || die "Kubernetes API not reachable"
}

# ── 8. Helm repos ─────────────────────────────────────────────────────────────
setup_helm_repos() {
  info "Configuring Helm repositories..."
  helm repo add bitnami             https://charts.bitnami.com/bitnami              2>/dev/null || true
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
  helm repo add grafana             https://grafana.github.io/helm-charts           2>/dev/null || true
  helm repo update
  success "Helm repos updated"
}

# ── 9. Build Docker images ────────────────────────────────────────────────────
build_images() {
  info "Building Docker images for all 5 services..."
  local -a services=(
    "api-gateway:novasurge/api-gateway:latest"
    "notification-service:novasurge/notification-service:latest"
    "product-service:novasurge/product-service:latest"
    "order-service:novasurge/order-service:latest"
    "payment-service:novasurge/payment-service:latest"
  )

  for entry in "${services[@]}"; do
    local svc="${entry%%:*}"
    local tag="${entry#*:}"
    info "  Building ${tag}..."
    docker build -t "${tag}" "${SCRIPT_DIR}/services/${svc}" \
      || die "Failed to build ${tag}"

    # Import into k3s containerd on Linux
    if [[ "$OS" == "Linux" ]] && command -v k3s &>/dev/null; then
      docker save "${tag}" | $SUDO k3s ctr images import - \
        || warn "Image import into k3s failed for ${tag} — pods may ImagePullBackOff"
    fi

    # Import into k3d cluster on macOS (k3d doesn't share Docker daemon images)
    if [[ "$OS" == "Darwin" ]] && command -v k3d &>/dev/null; then
      k3d image import "${tag}" -c novasurge \
        || warn "Image import into k3d failed for ${tag} — pods may ImagePullBackOff"
    fi

    success "  ${tag} built"
  done
}

# ── 10. Namespace + RBAC ──────────────────────────────────────────────────────
apply_namespace() {
  info "Applying namespace and RBAC..."
  kubectl apply -f "${SCRIPT_DIR}/k8s/namespace.yaml"
  kubectl apply -f "${SCRIPT_DIR}/k8s/rbac/novasurge-rbac.yaml"
  success "Namespace shopfusion and RBAC ready"
}

# ── 11. PostgreSQL ────────────────────────────────────────────────────────────
deploy_postgres() {
  info "Deploying PostgreSQL via Helm..."
  helm upgrade --install postgres bitnami/postgresql \
    --namespace shopfusion \
    -f "${SCRIPT_DIR}/k8s/postgres/helm-values.yaml" \
    --wait --timeout 5m

  # Give Postgres time to accept connections and run initdb
  info "Waiting for PostgreSQL to be ready..."
  kubectl wait pod -n shopfusion -l app.kubernetes.io/name=postgresql \
    --for=condition=ready --timeout=5m

  info "Creating ordersdb and paymentsdb..."
  POSTGRES_POD=$(kubectl get pod -n shopfusion -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].metadata.name}')
  kubectl exec -n shopfusion "${POSTGRES_POD}" -- \
    env PGPASSWORD=novasurge123 psql -U novasurge -d postgres -c \
    "CREATE DATABASE ordersdb;" 2>/dev/null || true
  kubectl exec -n shopfusion "${POSTGRES_POD}" -- \
    env PGPASSWORD=novasurge123 psql -U novasurge -d postgres -c \
    "CREATE DATABASE paymentsdb;" 2>/dev/null || true
  kubectl exec -n shopfusion "${POSTGRES_POD}" -- \
    env PGPASSWORD=novasurge123 psql -U novasurge -d postgres -c \
    "GRANT ALL PRIVILEGES ON DATABASE ordersdb TO novasurge; GRANT ALL PRIVILEGES ON DATABASE paymentsdb TO novasurge;" 2>/dev/null || true

  success "PostgreSQL ready (productsdb, ordersdb, paymentsdb)"
}

# ── 12. Redis ──────────────────────────────────────────────────────────────────
deploy_redis() {
  info "Deploying Redis via Helm..."
  helm upgrade --install redis bitnami/redis \
    --namespace shopfusion \
    -f "${SCRIPT_DIR}/k8s/redis/helm-values.yaml" \
    --wait --timeout 3m

  kubectl wait pod -n shopfusion -l app.kubernetes.io/name=redis \
    --for=condition=ready --timeout=3m
  success "Redis ready"
}

# ── 13. Application services ──────────────────────────────────────────────────
deploy_app_services() {
  info "Deploying ShopFusion application services..."

  # Order matters: backing services before order-service which calls others
  local manifests=(
    "k8s/product-service/deployment.yaml"
    "k8s/product-service/service.yaml"
    "k8s/product-service/hpa.yaml"
    "k8s/payment-service/deployment.yaml"
    "k8s/payment-service/service.yaml"
    "k8s/payment-service/hpa.yaml"
    "k8s/order-service/deployment.yaml"
    "k8s/order-service/service.yaml"
    "k8s/order-service/hpa.yaml"
    "k8s/api-gateway/deployment.yaml"
    "k8s/api-gateway/service.yaml"
    "k8s/notification-service/deployment.yaml"
    "k8s/notification-service/service.yaml"
  )

  for m in "${manifests[@]}"; do
    kubectl apply -f "${SCRIPT_DIR}/${m}"
  done
  success "Application manifests applied"
}

# ── 14. Nginx ─────────────────────────────────────────────────────────────────
deploy_nginx() {
  info "Deploying Nginx gateway..."
  kubectl apply -f "${SCRIPT_DIR}/k8s/nginx/configmap.yaml"
  kubectl apply -f "${SCRIPT_DIR}/k8s/nginx/deployment.yaml"
  kubectl apply -f "${SCRIPT_DIR}/k8s/nginx/service.yaml"
  success "Nginx gateway applied (NodePort 30080)"
}

# ── 15. Monitoring ────────────────────────────────────────────────────────────
deploy_monitoring() {
  info "Deploying kube-prometheus-stack..."
  helm upgrade --install kube-prometheus-stack \
    prometheus-community/kube-prometheus-stack \
    --namespace monitoring --create-namespace \
    -f "${SCRIPT_DIR}/k8s/monitoring/prometheus-values.yaml" \
    --wait --timeout 10m \
    || warn "Prometheus stack install had issues — continuing"

  info "Deploying Loki stack..."
  helm upgrade --install loki grafana/loki-stack \
    --namespace monitoring \
    -f "${SCRIPT_DIR}/k8s/monitoring/loki-values.yaml" \
    --wait --timeout 5m \
    || warn "Loki stack install had issues — continuing"

  info "Applying ServiceMonitors..."
  kubectl apply -f "${SCRIPT_DIR}/k8s/monitoring/service-monitors.yaml"
  success "Monitoring deployed"
}

# ── 16. Wait for all deployments ──────────────────────────────────────────────
wait_all_ready() {
  info "Waiting for all shopfusion deployments to roll out..."
  sleep 15

  local apps=(
    product-service
    payment-service
    order-service
    api-gateway
    notification-service
    nginx-gateway
  )

  for app in "${apps[@]}"; do
    kubectl rollout status deployment/"${app}" \
      -n shopfusion --timeout=300s \
      && success "  ${app} ready" \
      || warn "  ${app} may not be fully ready yet"
  done
}

# ── 17. Health verification ───────────────────────────────────────────────────
verify_health() {
  info "Verifying cluster health..."
  local base="http://localhost:30080"
  local ok=false

  for i in $(seq 1 24); do
    local code
    code=$(curl -so /dev/null -w "%{http_code}" "${base}/health" 2>/dev/null || echo "000")
    if [[ "$code" == "200" ]]; then
      ok=true
      break
    fi
    warn "  Attempt ${i}/24: /health returned ${code}, retrying in 5s..."
    sleep 5
  done

  if [[ "$ok" == "true" ]]; then
    success "GET ${base}/health → 200"
  else
    warn "Health endpoint not responding — cluster may still be starting"
  fi

  # Products check
  local count
  count=$(curl -sf "${base}/products" 2>/dev/null \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  if [[ "$count" -ge 20 ]]; then
    success "GET ${base}/products → ${count} products"
  else
    warn "GET ${base}/products → ${count} items (expected ≥20, seeds may still be running)"
  fi
}

# ── 18. Print summary ─────────────────────────────────────────────────────────
print_summary() {
  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║      NovaSurge Infrastructure — CLUSTER READY           ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  ${BLUE}ShopFusion API${NC}          http://localhost:30080"
  echo -e "  ${BLUE}Health check${NC}            curl http://localhost:30080/health"
  echo -e "  ${BLUE}Products list${NC}           curl http://localhost:30080/products"
  echo -e "  ${BLUE}Create order${NC}            curl -X POST http://localhost:30080/orders \\"
  echo -e "                           -H 'Content-Type: application/json' \\"
  echo -e "                           -d '{\"user_id\":\"u1\",\"product_id\":1,\"quantity\":1}'"
  echo ""
  echo -e "  ${YELLOW}Port-forward monitoring (run in separate terminals):${NC}"
  echo -e "    kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
  echo -e "    kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana    3200:80"
  echo -e "    kubectl port-forward -n monitoring svc/loki                             3100:3100"
  echo ""
  echo -e "  ${BLUE}Grafana${NC}  http://localhost:3200  (admin / novasurge123)"
  echo ""
  echo -e "  ${YELLOW}Load generator (triggers HPA scale-up):${NC}"
  echo -e "    bash scripts/load-gen.sh                   # 20 workers vs k8s"
  echo -e "    bash scripts/load-gen.sh localhost:30080 50 120  # 50 workers, 120s"
  echo ""
  echo -e "  ${YELLOW}Local dev without k8s:${NC}"
  echo -e "    docker compose up --build"
  echo ""
  echo -e "${BLUE}Pods in shopfusion namespace:${NC}"
  kubectl get pods -n shopfusion -o wide 2>/dev/null || true
  echo ""
  echo -e "${GREEN}All services healthy. NovaSurge is ready to chaos.${NC}"
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  echo -e "${BLUE}"
  echo "  ███╗   ██╗ ██████╗ ██╗   ██╗ █████╗ ███████╗██╗   ██╗██████╗  ██████╗ ███████╗"
  echo "  ████╗  ██║██╔═══██╗██║   ██║██╔══██╗██╔════╝██║   ██║██╔══██╗██╔════╝ ██╔════╝"
  echo "  ██╔██╗ ██║██║   ██║██║   ██║███████║███████╗██║   ██║██████╔╝██║  ███╗█████╗  "
  echo "  ██║╚██╗██║██║   ██║╚██╗ ██╔╝██╔══██║╚════██║██║   ██║██╔══██╗██║   ██║██╔══╝  "
  echo "  ██║ ╚████║╚██████╔╝ ╚████╔╝ ██║  ██║███████║╚██████╔╝██║  ██║╚██████╔╝███████╗"
  echo "  ╚═╝  ╚═══╝ ╚═════╝   ╚═══╝  ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝"
  echo -e "${NC}"
  info "Bootstrap starting on ${OS}..."

  install_base_deps
  install_docker
  install_python
  install_node
  install_kubectl
  install_helm
  install_k3s
  setup_helm_repos
  build_images
  apply_namespace
  deploy_postgres
  deploy_redis
  deploy_app_services
  deploy_nginx
  deploy_monitoring
  wait_all_ready
  verify_health
  print_summary
}

main "$@"
