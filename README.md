# NovaSurge

**Autonomous Chaos Engineering & Self-Healing Platform**

NovaSurge is an intelligent chaos engineering system that not only injects failures into microservice applications but detects, explains, and heals them in real time — while narrating its reasoning live.

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-20-green.svg)](https://nodejs.org/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-k3s-orange.svg)](https://k3s.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What We Built

NovaSurge demonstrates a complete **inject → detect → decide → recover** loop for autonomous resilience engineering:

1. **ShopFusion** — A 5-service e-commerce microservices application running on Kubernetes
2. **Chaos Injectors** — 5 types of real Kubernetes-native failure injection (pod deletion, CPU throttling, network partitions, latency injection, replica reduction)
3. **ML Anomaly Detection** — Isolation Forest + LSTM autoencoder trained on live telemetry
4. **Autonomous Decision Engine** — Safety guardrails, root cause analysis, and SLA-aware remediation
5. **Real-time Dashboard** — React-based UI with WebSocket streaming showing anomaly scores, reasoning feed, and service dependency graph

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        NovaSurge Platform                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   Chaos      │───▶│      ML      │───▶│   Decision   │       │
│  │  Injectors   │    │   Pipeline   │    │    Engine    │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌─────────────────────────────────────────────────────┐       │
│  │              ShopFusion Microservices                │       │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │       │
│  │  │  API    │ │ Product │ │  Order  │ │ Payment │  │       │
│  │  │ Gateway │ │ Service │ │ Service │ │ Service │  │       │
│  │  │ :3000   │ │ :8001   │ │ :8002   │ │ :8003   │  │       │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘  │       │
│  │       │           │           │           │        │       │
│  │       └───────────┴───────────┴───────────┘        │       │
│  │                   PostgreSQL + Redis                │       │
│  └─────────────────────────────────────────────────────┘       │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────┐       │
│  │            Prometheus + Grafana + Loki               │       │
│  └─────────────────────────────────────────────────────┘       │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────┐       │
│  │         React Dashboard (WebSocket Stream)           │       │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │       │
│  │  │Anomaly  │ │Reasoning│ │ Health  │ │Decision │   │       │
│  │  │ Chart   │ │  Feed   │ │  Grid   │ │  Trace  │   │       │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘   │       │
│  └─────────────────────────────────────────────────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Ubuntu 22.04+ or macOS 12+
- 8GB RAM minimum (16GB recommended)
- Internet connection for initial setup

### Bootstrap (One Command)

```bash
# Clone and enter the repository
cd /path/to/novasurge

# Run the bootstrap script - installs everything
bash bootstrap.sh
```

This script will:
1. Install Docker, k3s/minikube, kubectl, Helm
2. Deploy Prometheus + Loki monitoring stack
3. Deploy PostgreSQL and Redis
4. Build and deploy all 5 ShopFusion services
5. Initialize ML models with synthetic baseline data

### Start the Platform

```bash
# Activate virtual environment
source venv/bin/activate

# Start NovaSurge API (Terminal 1)
make api
# OR: cd novasurge && python -m api.main

# Start Dashboard (Terminal 2)
make dashboard
# OR: cd dashboard && npm run dev

# Run the 5-round chaos demo (Terminal 3)
make demo
# OR: cd novasurge && python -m orchestrator
```

### Access Points

| Service | URL | Notes |
|---------|-----|-------|
| Dashboard | http://localhost:5173 | Main UI - Open this first |
| NovaSurge API | http://localhost:8000 | REST API + WebSocket |
| API Gateway | http://localhost:3000 | ShopFusion entry point |
| Prometheus | http://localhost:9090 | Requires port-forward |
| Grafana | http://localhost:3000 | Requires port-forward |

---

## Demo Structure (7 Minutes)

1. **Minute 1**: Open dashboard fullscreen, explain the system
2. **Minutes 2-3**: Run Round 1 live, let Reasoning Feed narrate
3. **Minute 4**: Show dependency graph blast radius animation
4. **Minutes 5-6**: Run Rounds 2 and 3, point to Decision Trace Table
5. **Minute 7**: Show all 5 completed rounds, close with value proposition

```bash
# Run the complete demo
bash scripts/demo.sh
```

---

## Project Structure

```
novasurge/
├── services/           # ShopFusion microservices
│   ├── api-gateway/    # Node.js/Express entry point
│   ├── product-service/# Python/FastAPI + PostgreSQL/Redis
│   ├── order-service/  # Python/FastAPI + calls product/payment
│   ├── payment-service/# Python/FastAPI + publishes events
│   └── notification-service/ # Node.js + Redis pub/sub
├── k8s/                # Kubernetes manifests
│   ├── namespace.yaml
│   ├── api-gateway/
│   ├── product-service/
│   ├── order-service/
│   ├── payment-service/
│   ├── notification-service/
│   ├── postgres/
│   ├── redis/
│   ├── nginx/
│   ├── monitoring/     # Prometheus + Loki values
│   └── rbac/           # NovaSurge service account
├── novasurge/          # Platform code
│   ├── chaos/          # Failure injectors
│   │   ├── injectors/  # 5 chaos injection types
│   │   └── load_gen.py # Traffic generator
│   ├── remediators/  # 4 remediation actions
│   ├── ml/             # ML pipeline
│   │   ├── generate_synthetic.py
│   │   ├── train_iforest.py
│   │   ├── train_lstm.py
│   │   ├── inference.py
│   │   └── prometheus_fetcher.py
│   ├── api/            # FastAPI backend
│   ├── decision_engine.py
│   ├── reasoning.py    # Narrative generation
│   ├── rca.py          # Root cause analysis
│   ├── orchestrator.py # 5-round orchestration
│   ├── data/           # Runtime data
│   ├── models/         # Trained ML models
│   ├── state/          # Current anomaly state
│   └── logs/           # Round summaries
├── dashboard/          # React + Vite + Tailwind + D3
├── scripts/
│   └── demo.sh         # Demo runner
├── bootstrap.sh        # One-command setup
├── Makefile           # Quick commands
└── README.md
```

---

## Key Features

### 1. Autonomous Reasoning Feed
Every decision is narrated in plain English in real time. Generated from deterministic Python templates — no LLM, fully offline.

### 2. Root Cause Analysis Engine
Correlates metrics + logs + service dependency graph to identify the true origin of failures before remediation.

### 3. Intelligent Failure Strategy
Ranks services by downstream dependency count and current load, injecting against highest-ranked services for purposeful chaos.

### 4. SLA/SLO Awareness
Remediation decisions ordered by business impact weights:
- payment-service: 10
- api-gateway: 9
- order-service: 8
- product-service: 6
- notification-service: 2

### 5. Safety Guardrails
Before any remediation:
- Checks for duplicate active remediations
- Ensures minimum replica safety
- Checks recent failure memory
- Implements cascade protection

### 6. Service Dependency Graph
Live D3.js force graph with:
- Node colors: green=healthy, amber=degraded, red=anomaly
- Edge thickness: proportional to request rate
- Blast radius animation on injection

---

## ML Pipeline

### Feature Engineering (per 10s window per service)
- `http_request_rate`: Request count
- `error_rate`: Error percentage
- `p99_latency`: 99th percentile latency
- `cpu_usage`: CPU utilization
- `memory_usage`: Memory utilization
- `active_connections`: Open connections

### Models
1. **Isolation Forest**: `score < -0.15` → anomaly flag
2. **LSTM Autoencoder**: Reconstruction error > 2σ → predictive flag
3. **Anomaly Classification**: Pattern-based type detection

### Training
```bash
# Generate synthetic baseline (2000 samples)
python novasurge/ml/generate_synthetic.py

# Train Isolation Forest
python novasurge/ml/train_iforest.py

# Train LSTM
python novasurge/ml/train_lstm.py
```

---

## Chaos Injectors

| Injector | Description | Reversible |
|----------|-------------|------------|
| Pod Deletion | Delete random pod from deployment | Yes (K8s reschedules) |
| CPU Throttle | Patch resource limits to 50m CPU | Yes |
| Network Partition | Create blocking NetworkPolicy | Yes |
| Latency Injection | tc netem 500ms delay in container | Yes |
| Replica Reduction | Patch HPA min/max to 1 | Yes |

## Remediators

| Remediator | Action |
|------------|--------|
| Pod Restart | Delete unhealthy pod, poll for replacement |
| HPA Scale-Out | Patch maxReplicas=6, poll for ready |
| Traffic Reroute | Update Nginx ConfigMap, reload |
| Cache Flush | Redis FLUSHDB on affected service |

---

## API Endpoints

### REST
- `GET /` — API status
- `GET /health` — Health check
- `GET /anomaly/current` — Current anomaly state
- `GET /anomaly/history` — Anomaly history
- `GET /rounds` — Completed round summaries
- `GET /metrics/current` — Current metrics snapshot

### WebSocket
- `WS /ws/stream` — Real-time streaming (5-second interval)

---

## Development

```bash
# Install dependencies
make install

# Start individual components
make api          # API server on :8000
make dashboard    # Dashboard on :5173
make ml-inference # ML inference loop

# Kubernetes operations
make k8s-deploy   # Deploy to K8s
make k8s-delete   # Delete from K8s
make k8s-logs     # View logs

# Testing
make demo         # Run 5-round demo
make demo-dry     # Demo in dry-run mode
make test         # Run tests
make clean        # Clean up logs and data
```

---

## Team

Built in 36 hours by a 4-person team:

- **Person 1**: Infrastructure (K8s, Helm, monitoring, bootstrap)
- **Person 2**: Chaos + Remediation (injectors, remediators, orchestrator)
- **Person 3**: ML + Backend (synthetic data, models, inference, API)
- **Person 4**: Dashboard + Integration (React, D3, demo script, documentation)

---

## License

MIT License — Built for learning and demonstration purposes.

---

## Acknowledgments

- [Prometheus](https://prometheus.io/) — Metrics collection
- [Grafana](https://grafana.com/) — Visualization
- [k3s](https://k3s.io/) — Lightweight Kubernetes
- [scikit-learn](https://scikit-learn.org/) — Isolation Forest
- [PyTorch](https://pytorch.org/) — LSTM autoencoder
