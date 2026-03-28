# NovaSurge — Judging Evaluation Guide

**Autonomous Chaos Engineering & Self-Healing Platform**

---

## One-Line Pitch

NovaSurge is an autonomous chaos engineering system that not only breaks microservices intentionally but detects, explains, and heals them in real time — while narrating its reasoning live.

---

## Evaluation Criteria Mapping

### 1. Technical Complexity

| Requirement | Implementation | Evidence |
|-------------|----------------|----------|
| Multi-service K8s application | ✅ 5 services + 2 databases + ingress | `k8s/` manifests |
| Real HTTP inter-service comms | ✅ Order→Product/Payment calls | `order-service/main.py:142-176` |
| Real databases (PostgreSQL, Redis) | ✅ 3 PG databases + Redis cache/pub-sub | `k8s/postgres/`, `k8s/redis/` |
| K8s-native failure injection | ✅ 5 injector types | `novasurge/chaos/injectors/` |
| Prometheus + Loki observability | ✅ Full metrics + structured logs | `k8s/monitoring/` |
| Own ML anomaly detector | ✅ Isolation Forest + LSTM | `novasurge/ml/` |
| Autonomous decision engine | ✅ 4 remediators + 4 guardrails | `novasurge/decision_engine.py` |
| Full inject→detect→decide→recover | ✅ 5 rounds implemented | `novasurge/orchestrator.py` |
| Real-time dashboard | ✅ WebSocket streaming + D3 | `dashboard/src/` |

**Differentiating Technical Features:**

1. **ML Pipeline**: Isolation Forest (scikit-learn) + LSTM Autoencoder (PyTorch) with real-time inference
2. **Root Cause Analysis**: Service dependency graph traversal to identify true failure origin
3. **Intelligent Failure Strategy**: Ranks services by blast radius before injection
4. **4-Layer Safety Guardrails**: Duplicate detection, replica safety, failure memory, cascade protection
5. **SLA-Aware Remediation**: Business impact weights prioritize payment-service over notifications

### 2. Innovation

**What's Different from Existing Tools?**

| Tool | Approach | NovaSurge Difference |
|------|----------|---------------------|
| Chaos Monkey | Random failure injection | **Intelligent** — profiles system first, targets highest blast radius |
| Gremlin | Manual/scheduled chaos | **Autonomous** — self-healing without human intervention |
| Litmus | Pre-defined experiments | **Adaptive** — ML detects and classifies failures in real time |
| Datadog/etc | Passive monitoring | **Active** — not just observes, but heals and narrates reasoning |

**Key Innovations:**

1. **Autonomous Reasoning Feed**: Plain English narration of every decision using deterministic templates (no LLM API dependency)
2. **Predictive Detection**: LSTM forecasts anomalies 60 seconds ahead
3. **Dependency-Aware RCA**: Walks call graph upstream to find true failure origin
4. **Self-Correcting Remediation**: Tracks success/failure in SQLite, adjusts confidence scores

### 3. Demo Quality

**7-Minute Demo Structure:**

| Minute | Activity | Visual |
|--------|----------|--------|
| 1 | Opening statement, dashboard fullscreen | Reasoning Feed panel |
| 2-3 | Run Round 1 (pod deletion → order-service) | Live anomaly detection, scores updating |
| 4 | Show blast radius on dependency graph | Node turns red, edges pulse amber |
| 5-6 | Run Rounds 2-3 | Decision Trace Table appending rows |
| 7 | Summary of all 5 rounds | Completed table, recovery times |

**Demo Commands:**

```bash
# Terminal 1: Start API
source venv/bin/activate
cd novasurge && python -m api.main

# Terminal 2: Start Dashboard
cd dashboard && npm run dev

# Terminal 3: Run Demo
cd novasurge && python -m orchestrator
# OR: make demo
```

**Dashboard Panels:**

1. **Autonomous Reasoning Feed** (center, largest) — Live narration of decisions
2. **Anomaly Score Chart** — Real-time Isolation Forest scores per service
3. **System Health Grid** — 5 service cards with status
4. **Decision Trace Table** — Round history with timestamps
5. **Service Dependency Graph** — D3 force graph with blast radius
6. **LSTM Prediction Horizon** — 60-second prediction chart

### 4. Code Quality

**Architecture Patterns:**
- Clean separation: injectors → ML → decision → remediators
- Dependency injection via K8s Python client
- Async/await for concurrent health polling
- SQLite for persistent state, JSON for runtime state
- WebSocket for real-time dashboard updates

**Testing Approach:**
- `--dry-run` mode for safe testing
- Mock K8s client for CI/CD
- Synthetic data generator for reproducible ML training

**Documentation:**
- Inline comments on all non-obvious decisions
- Module-level docstrings
- README with architecture diagrams
- This JUDGING.md for evaluators

---

## Technical Stack

| Layer | Technology |
|-------|------------|
| Orchestration | Kubernetes (k3s/minikube) |
| Services | Python (FastAPI) + Node.js (Express) |
| Databases | PostgreSQL, Redis |
| Monitoring | Prometheus + Grafana + Loki |
| ML | scikit-learn (Isolation Forest), PyTorch (LSTM) |
| Backend | FastAPI, WebSocket |
| Frontend | React, Vite, Tailwind CSS, Recharts, D3.js |
| Deployment | Helm, kubectl, Docker |

---

## File Structure for Navigation

```
Key Files for Evaluation:
├── bootstrap.sh                    # One-command setup
├── novasurge/
│   ├── orchestrator.py            # Main 5-round demo loop
│   ├── decision_engine.py         # Guardrails + decision logic
│   ├── reasoning.py               # Narrative generation
│   ├── rca.py                     # Root cause analysis
│   ├── chaos/injectors/           # 5 failure types
│   ├── remediators/               # 4 healing actions
│   ├── ml/                        # ML pipeline
│   │   ├── train_iforest.py
│   │   ├── train_lstm.py
│   │   └── inference.py
│   └── api/main.py                # FastAPI + WebSocket
├── dashboard/
│   └── src/
│       ├── App.jsx                # Main dashboard
│       ├── hooks/useNovaSurgeStream.js
│       └── components/            # 6 panels
└── k8s/                           # All K8s manifests
```

---

## Running the Evaluation

### Quick Start (5 minutes)

```bash
# 1. Bootstrap (if not done)
bash bootstrap.sh

# 2. Start API (Terminal 1)
source venv/bin/activate
cd novasurge && python -m api.main

# 3. Start Dashboard (Terminal 2)
cd dashboard && npm run dev

# 4. Run Demo (Terminal 3)
cd novasurge && python -m orchestrator
```

### Dry Run Mode (Safe Testing)

```bash
cd novasurge && python -m orchestrator --dry-run
```

---

## Performance Metrics

**Detection Latency**: ~15 seconds (prometheus scrape + inference)
**Decision Latency**: ~1 second (guardrails + RCA + scoring)
**Remediation Latency**: ~10-60 seconds (pod restart to health check)
**End-to-End Recovery**: ~30-90 seconds per round

**ML Model Performance**:
- Isolation Forest: 95% detection rate at 5% contamination
- LSTM: 2σ threshold catches ~90% of emerging anomalies

---

## Known Limitations (Transparency)

1. **Synthetic Baseline**: Uses generated data for initial training; would benefit from real production baselines
2. **Mock K8s Fallback**: Can run in mock mode for demo without real cluster
3. **Single-Node LSTM**: CPU-only PyTorch; GPU would enable larger models
4. **Static Dependency Graph**: Service topology is hardcoded; dynamic discovery would be better

---

## Value Proposition

**For Platform Teams:**
- Validates resilience before production incidents
- Reduces mean-time-to-recovery (MTTR) via automation
- Provides audit trail of all chaos experiments

**For Developers:**
- Catches integration failures early
- Documents actual vs expected behavior
- Builds confidence in deployment safety

**For Business:**
- Protects revenue by prioritizing payment path remediation
- Reduces on-call burden via autonomous healing
- Demonstrates regulatory compliance for availability

---

## Contact

Built for a 36-hour hackathon by a 4-person team.

Questions? Check `README.md` for architecture details or run `make help` for commands.
