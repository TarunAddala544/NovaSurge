.PHONY: setup status logs teardown \
        port-forward-prometheus port-forward-grafana port-forward-loki \
        build-images apply-manifests health-check

# ── Primary target ─────────────────────────────────────────────────────────────
setup:
	@chmod +x bootstrap.sh && bash bootstrap.sh

# ── Cluster status ─────────────────────────────────────────────────────────────
status:
	@echo "=== All Pods ==="
	@kubectl get pods -A -o wide
	@echo ""
	@echo "=== shopfusion Services ==="
	@kubectl get svc -n shopfusion
	@echo ""
	@echo "=== HPAs ==="
	@kubectl get hpa -n shopfusion 2>/dev/null || true

# ── Logs ────────────────────────────────────────────────────────────────────────
logs:
	@echo "════════════ api-gateway ════════════"
	@kubectl logs -n shopfusion -l app=api-gateway --tail=50 --prefix=true 2>/dev/null || true
	@echo ""
	@echo "════════════ product-service ════════════"
	@kubectl logs -n shopfusion -l app=product-service --tail=50 --prefix=true 2>/dev/null || true
	@echo ""
	@echo "════════════ order-service ════════════"
	@kubectl logs -n shopfusion -l app=order-service --tail=50 --prefix=true 2>/dev/null || true
	@echo ""
	@echo "════════════ payment-service ════════════"
	@kubectl logs -n shopfusion -l app=payment-service --tail=50 --prefix=true 2>/dev/null || true
	@echo ""
	@echo "════════════ notification-service ════════════"
	@kubectl logs -n shopfusion -l app=notification-service --tail=50 --prefix=true 2>/dev/null || true

# ── Teardown ────────────────────────────────────────────────────────────────────
teardown:
	@echo "Tearing down NovaSurge cluster..."
	@if command -v k3s-uninstall.sh &>/dev/null; then \
		sudo k3s-uninstall.sh; \
		echo "k3s uninstalled"; \
	elif command -v k3d &>/dev/null; then \
		k3d cluster delete novasurge && echo "k3d cluster deleted"; \
	else \
		echo "No k3s or k3d found to uninstall"; \
	fi

# ── Port forwards ───────────────────────────────────────────────────────────────
port-forward-prometheus:
	@echo "Prometheus available at http://localhost:9090"
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090

port-forward-grafana:
	@echo "Grafana available at http://localhost:3200 (admin/novasurge123)"
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3200:80

port-forward-loki:
	@echo "Loki available at http://localhost:3100"
	kubectl port-forward -n monitoring svc/loki 3100:3100

# ── Build only ─────────────────────────────────────────────────────────────────
build-images:
	@for svc in api-gateway notification-service product-service order-service payment-service; do \
		echo "Building novasurge/$$svc:latest..."; \
		docker build -t novasurge/$$svc:latest services/$$svc; \
	done

# ── Apply manifests only ───────────────────────────────────────────────────────
apply-manifests:
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/rbac/novasurge-rbac.yaml
	kubectl apply -f k8s/product-service/
	kubectl apply -f k8s/order-service/
	kubectl apply -f k8s/payment-service/
	kubectl apply -f k8s/api-gateway/deployment.yaml
	kubectl apply -f k8s/api-gateway/service.yaml
	kubectl apply -f k8s/notification-service/
	kubectl apply -f k8s/nginx/
	kubectl apply -f k8s/monitoring/service-monitors.yaml

# ── Health check ───────────────────────────────────────────────────────────────
health-check:
	@echo "Testing endpoints..."
	@echo -n "  /health:   " && curl -sf http://localhost:30080/health | python3 -m json.tool 2>/dev/null || echo "FAILED"
	@echo -n "  /products: " && curl -sf http://localhost:30080/products | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'{len(d)} products')" 2>/dev/null || echo "FAILED"
	@echo ""
	@echo "Per-service metrics:"
	@for port in 3000 3001 8001 8002 8003; do \
		svc=$$(kubectl get pod -n shopfusion -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
		echo "  Checking port $$port ..."; \
	done

# ── Reload nginx config ─────────────────────────────────────────────────────────
reload-nginx:
	kubectl rollout restart deployment/nginx-gateway -n shopfusion
	kubectl rollout status deployment/nginx-gateway -n shopfusion

# ── Watch pods ─────────────────────────────────────────────────────────────────
watch:
	watch -n 2 'kubectl get pods -n shopfusion -o wide'
