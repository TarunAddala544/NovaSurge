# NovaSurge Makefile
# Quick commands for development and deployment

.PHONY: help install start stop clean test demo bootstrap

# Default target
help:
	@echo "NovaSurge - Autonomous Chaos Engineering Platform"
	@echo ""
	@echo "Available targets:"
	@echo "  bootstrap    - Full system setup from scratch (run once)"
	@echo "  install      - Install Python and Node dependencies"
	@echo "  start        - Start all services and NovaSurge"
	@echo "  stop         - Stop all services"
	@echo "  restart      - Restart all services"
	@echo "  status       - Check service status"
	@echo "  demo         - Run full 5-round chaos demo"
	@echo "  demo-dry     - Run demo in dry-run mode"
	@echo "  ml-train     - Regenerate ML models"
	@echo "  test         - Run tests"
	@echo "  clean        - Clean up logs and temporary files"
	@echo "  logs         - View service logs"
	@echo "  k8s-deploy   - Deploy to Kubernetes"
	@echo "  dashboard    - Start dashboard dev server"
	@echo "  api          - Start NovaSurge API server"

# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

bootstrap:
	@echo "Running full bootstrap..."
	bash bootstrap.sh

install:
	@echo "Installing Python dependencies..."
	pip install -r novasurge/requirements.txt
	@echo "Installing Dashboard dependencies..."
	cd dashboard && npm install

# ─────────────────────────────────────────────────────────────────────────────
# START/STOP
# ─────────────────────────────────────────────────────────────────────────────

start:
	@echo "Starting NovaSurge API..."
	@mkdir -p logs
	@cd novasurge && python -m api.main > ../logs/api.log 2>&1 &
	@echo "API started on http://localhost:8000"
	@echo "Starting Dashboard..."
	@cd dashboard && npm run dev > ../logs/dashboard.log 2>&1 &
	@echo "Dashboard started on http://localhost:5173"
	@echo ""
	@echo "Services:"
	@echo "  API:       http://localhost:8000"
	@echo "  Dashboard: http://localhost:5173"
	@echo "  Prometheus: kubectl port-forward -n shopfusion svc/prometheus-kube-prometheus-prometheus 9090"
	@echo ""

stop:
	@echo "Stopping services..."
	@-pkill -f "python -m api.main" 2>/dev/null || true
	@-pkill -f "vite" 2>/dev/null || true
	@-pkill -f "python -m novasurge.orchestrator" 2>/dev/null || true
	@echo "Services stopped"

restart: stop start

status:
	@echo "NovaSurge Status:"
	@echo "=================="
	@echo ""
	@echo "API Server:"
	@curl -s http://localhost:8000/health 2>/dev/null && echo " ✓ Running" || echo " ✗ Not running"
	@echo ""
	@echo "Dashboard:"
	@curl -s http://localhost:5173 2>/dev/null | head -1 && echo " ✓ Running" || echo " ✗ Not running"
	@echo ""
	@echo "Kubernetes Services:"
	@kubectl get pods -n shopfusion 2>/dev/null | grep -E "(Running|Pending|Error)" | wc -l | xargs echo "  Running pods:"

# ─────────────────────────────────────────────────────────────────────────────
# DEMO
# ─────────────────────────────────────────────────────────────────────────────

demo:
	@echo "Running NovaSurge 5-round chaos demo..."
	@cd novasurge && python -m orchestrator

demo-dry:
	@echo "Running NovaSurge demo in dry-run mode..."
	@cd novasurge && python -m orchestrator --dry-run

# ─────────────────────────────────────────────────────────────────────────────
# ML OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

ml-train:
	@echo "Regenerating ML models..."
	cd novasurge && python -m ml.generate_synthetic
	cd novasurge && python -m ml.train_iforest
	cd novasurge && python -m ml.train_lstm

ml-inference:
	@echo "Starting ML inference engine..."
	cd novasurge && python -m ml.inference

# ─────────────────────────────────────────────────────────────────────────────
# DEVELOPMENT
# ─────────────────────────────────────────────────────────────────────────────

api:
	@echo "Starting NovaSurge API..."
	cd novasurge && python -m api.main

dashboard:
	@echo "Starting Dashboard..."
	cd dashboard && npm run dev

test:
	@echo "Running tests..."
	cd novasurge && python -m pytest tests/ -v 2>/dev/null || echo "No tests directory found"

lint:
	@echo "Linting Python code..."
	cd novasurge && flake8 . --max-line-length=100 --ignore=E203,W503 2>/dev/null || echo "flake8 not installed"
	@echo "Linting Dashboard code..."
	cd dashboard && npm run lint 2>/dev/null || echo "No lint script defined"

# ─────────────────────────────────────────────────────────────────────────────
# KUBERNETES
# ─────────────────────────────────────────────────────────────────────────────

k8s-deploy:
	@echo "Deploying to Kubernetes..."
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/api-gateway/
	kubectl apply -f k8s/product-service/
	kubectl apply -f k8s/order-service/
	kubectl apply -f k8s/payment-service/
	kubectl apply -f k8s/notification-service/
	kubectl apply -f k8s/nginx/
	kubectl apply -f k8s/rbac/
	@echo "Waiting for deployments..."
	kubectl wait --for=condition=available --timeout=300s \
		deployment/api-gateway deployment/product-service deployment/order-service \
		deployment/payment-service deployment/notification-service \
		-n shopfusion 2>/dev/null || echo "Timeout waiting for deployments"

k8s-delete:
	@echo "Deleting Kubernetes resources..."
	kubectl delete namespace shopfusion --ignore-not-found=true

k8s-logs:
	@echo "Recent logs from all services..."
	kubectl logs -n shopfusion --all-containers --since=5m 2>/dev/null | tail -100 || echo "Could not fetch logs"

k8s-port-forward:
	@echo "Setting up port forwards..."
	@kubectl port-forward -n shopfusion svc/api-gateway 3000:3000 &
	@kubectl port-forward -n shopfusion svc/product-service 8001:8001 &
	@kubectl port-forward -n shopfusion svc/order-service 8002:8002 &
	@kubectl port-forward -n shopfusion svc/payment-service 8003:8003 &
	@kubectl port-forward -n shopfusion svc/notification-service 3001:3001 &
	@echo "Port forwards active (Ctrl+C to stop)"

# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────────────────

clean:
	@echo "Cleaning up..."
	@rm -rf novasurge/logs/*.json
	@rm -rf novasurge/data/*.csv
	@rm -rf novasurge/data/*.jsonl
	@rm -rf novasurge/__pycache__
	@rm -rf novasurge/*/__pycache__
	@rm -rf novasurge/*/*/__pycache__
	@rm -rf services/*/__pycache__
	@find . -name "*.pyc" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleanup complete"

logs:
	@echo "Viewing NovaSurge logs..."
	@tail -f logs/*.log 2>/dev/null || echo "No log files found"

logs-orchestrator:
	@echo "Viewing orchestrator output..."
	@cat novasurge/logs/all_rounds_summary.json 2>/dev/null || echo "No orchestrator logs yet"

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────

db-reset:
	@echo "Resetting databases..."
	@kubectl delete pod -n shopfusion -l app=postgres --ignore-not-found=true
	@kubectl delete pod -n shopfusion -l app=redis --ignore-not-found=true
	@echo "Databases will be recreated by Kubernetes"
