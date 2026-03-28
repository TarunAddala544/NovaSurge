#!/bin/bash
# NovaSurge Bootstrap Script
# Installs and configures everything from scratch on a clean Ubuntu/macOS machine
# Run: bash bootstrap.sh

set -e  # Exit on any error

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              NOVASURGE BOOTSTRAP SCRIPT                        ║"
echo "║   Autonomous Chaos Engineering Platform Setup                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Detect OS
OS=""
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
else
    log_error "Unsupported OS: $OSTYPE"
    exit 1
fi
log_info "Detected OS: $OS"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Install System Dependencies
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 1: Installing system dependencies..."

if [[ "$OS" == "linux" ]]; then
    # Ubuntu/Debian
    sudo apt-get update
    sudo apt-get install -y \
        curl \
        wget \
        apt-transport-https \
        ca-certificates \
        gnupg \
        lsb-release \
        software-properties-common \
        jq \
        git \
        build-essential \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3-pip \
        nodejs \
        npm
elif [[ "$OS" == "macos" ]]; then
    # macOS with Homebrew
    if ! command -v brew &> /dev/null; then
        log_info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    brew update
    brew install \
        curl \
        wget \
        jq \
        git \
        python@3.11 \
        node
fi

log_success "System dependencies installed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Install Docker
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 2: Installing Docker..."

if ! command -v docker &> /dev/null; then
    if [[ "$OS" == "linux" ]]; then
        # Install Docker
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker $USER
        rm get-docker.sh
        sudo systemctl enable docker
        sudo systemctl start docker
    elif [[ "$OS" == "macos" ]]; then
        brew install --cask docker
        log_warn "Please start Docker Desktop manually and continue"
        read -p "Press Enter when Docker is running..."
    fi
else
    log_warn "Docker already installed, skipping"
fi

log_success "Docker installed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Install k3s (lightweight Kubernetes)
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 3: Installing k3s..."

if ! command -v kubectl &> /dev/null; then
    if [[ "$OS" == "linux" ]]; then
        # Install k3s
        curl -sfL https://get.k3s.io | sh -
        sudo chmod 644 /etc/rancher/k3s/k3s.yaml
        mkdir -p ~/.kube
        sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
        sudo chown $(id -u):$(id -g) ~/.kube/config
        export KUBECONFIG=~/.kube/config
    elif [[ "$OS" == "macos" ]]; then
        # Use minikube for macOS
        brew install kubectl
        brew install minikube
        minikube start --driver=docker --memory=4096 --cpus=4
    fi
else
    log_warn "kubectl already installed, skipping"
fi

log_success "Kubernetes (k3s/minikube) installed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Install Helm
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 4: Installing Helm..."

if ! command -v helm &> /dev/null; then
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
else
    log_warn "Helm already installed, skipping"
fi

log_success "Helm installed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Setup Python Environment
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 5: Setting up Python environment..."

PYTHON_VERSION=$(python3.11 --version 2>/dev/null || python3 --version 2>/dev/null || echo "unknown")
log_info "Python version: $PYTHON_VERSION"

# Create virtual environment
python3.11 -m venv venv || python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install Python dependencies
log_info "Installing Python dependencies..."
pip install -r novasurge/requirements.txt

log_success "Python environment configured"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6: Install Node.js Dependencies (Dashboard)
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 6: Setting up Dashboard (Node.js)..."

cd dashboard
npm install
cd ..

log_success "Dashboard dependencies installed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7: Deploy Monitoring Stack (Prometheus + Loki)
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 7: Deploying monitoring stack..."

# Add Helm repositories
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Create namespace
kubectl apply -f k8s/namespace.yaml

# Deploy Prometheus + Grafana
helm install prometheus prometheus-community/kube-prometheus-stack \
    --namespace shopfusion \
    --values k8s/monitoring/prometheus-values.yaml \
    --wait --timeout 600s || \
helm upgrade prometheus prometheus-community/kube-prometheus-stack \
    --namespace shopfusion \
    --values k8s/monitoring/prometheus-values.yaml \
    --wait --timeout 600s

# Deploy Loki
helm install loki grafana/loki-stack \
    --namespace shopfusion \
    --values k8s/monitoring/loki-values.yaml \
    --wait --timeout 600s || \
helm upgrade loki grafana/loki-stack \
    --namespace shopfusion \
    --values k8s/monitoring/loki-values.yaml \
    --wait --timeout 600s

log_success "Monitoring stack deployed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8: Deploy Databases (PostgreSQL + Redis)
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 8: Deploying databases..."

# Deploy PostgreSQL
helm install postgres oci://registry-1.docker.io/bitnamicharts/postgresql \
    --namespace shopfusion \
    --values k8s/postgres/helm-values.yaml \
    --wait --timeout 300s || \
helm upgrade postgres oci://registry-1.docker.io/bitnamicharts/postgresql \
    --namespace shopfusion \
    --values k8s/postgres/helm-values.yaml \
    --wait --timeout 300s

# Deploy Redis
helm install redis oci://registry-1.docker.io/bitnamicharts/redis \
    --namespace shopfusion \
    --values k8s/redis/helm-values.yaml \
    --wait --timeout 300s || \
helm upgrade redis oci://registry-1.docker.io/bitnamicharts/redis \
    --namespace shopfusion \
    --values k8s/redis/helm-values.yaml \
    --wait --timeout 300s

log_success "Databases deployed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9: Build and Deploy ShopFusion Services
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 9: Building and deploying ShopFusion services..."

# Build Docker images
SERVICES="api-gateway product-service order-service payment-service notification-service"

for service in $SERVICES; do
    log_info "Building $service..."
    docker build -t shopfusion/$service:latest \
        -f services/$service/Dockerfile \
        services/$service
done

# For k3s, we need to import images
if [[ "$OS" == "linux" ]]; then
    for service in $SERVICES; do
        sudo k3s ctr images import <<< "$(docker save shopfusion/$service:latest)" 2>/dev/null || true
    done
fi

# Deploy services
kubectl apply -f k8s/api-gateway/
kubectl apply -f k8s/product-service/
kubectl apply -f k8s/order-service/
kubectl apply -f k8s/payment-service/
kubectl apply -f k8s/notification-service/
kubectl apply -f k8s/nginx/

# Deploy RBAC for NovaSurge
kubectl apply -f k8s/rbac/novasurge-rbac.yaml

# Wait for deployments
log_info "Waiting for services to be ready..."
kubectl wait --for=condition=available --timeout=300s \
    deployment/api-gateway deployment/product-service deployment/order-service \
    deployment/payment-service deployment/notification-service \
    -n shopfusion

log_success "ShopFusion services deployed"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 10: Initialize ML Models
# ─────────────────────────────────────────────────────────────────────────────
log_info "Step 10: Initializing ML models..."

# Generate synthetic baseline data
python novasurge/ml/generate_synthetic.py

# Train Isolation Forest
python novasurge/ml/train_iforest.py

# Train LSTM (if PyTorch available)
python novasurge/ml/train_lstm.py || log_warn "LSTM training skipped (PyTorch not available)"

log_success "ML models initialized"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 11: Setup Complete
# ─────────────────────────────────────────────────────────────────────────────
echo
log_success "═══════════════════════════════════════════════════════════════"
log_success "                  NOVASURGE SETUP COMPLETE                       "
log_success "═══════════════════════════════════════════════════════════════"
echo
echo "ShopFusion application is running on Kubernetes"
echo "Prometheus: http://localhost:9090 (kubectl port-forward -n shopfusion svc/prometheus-kube-prometheus-prometheus 9090)"
echo "Grafana: http://localhost:3000 (kubectl port-forward -n shopfusion svc/prometheus-grafana 3000)"
echo "NovaSurge API: http://localhost:8000"
echo "NovaSurge Dashboard: http://localhost:5173"
echo
echo "To start the chaos orchestration:"
echo "  source venv/bin/activate"
echo "  python -m novasurge.orchestrator"
echo
echo "To run with dry-run mode:"
echo "  python -m novasurge.orchestrator --dry-run"
echo
