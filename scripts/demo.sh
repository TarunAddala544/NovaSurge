#!/bin/bash
# NovaSurge Demo Script
# Runs the full 5-round chaos engineering demonstration
# Usage: bash scripts/demo.sh [--dry-run]

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_header() { echo -e "${PURPLE}$1${NC}"; }
log_highlight() { echo -e "${CYAN}$1${NC}"; }

# Parse arguments
DRY_RUN=""
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN="--dry-run"
    log_warn "Running in DRY-RUN mode (no actual cluster changes)"
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo ""
log_header "╔════════════════════════════════════════════════════════════════════╗"
log_header "║                                                                    ║"
log_header "║   🌪  NOVASURGE — Autonomous Chaos Engineering Demo  🌪             ║"
log_header "║                                                                    ║"
log_header "║   Inject → Detect → Analyze → Decide → Recover → Narrate          ║"
log_header "║                                                                    ║"
log_header "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
log_info "Checking prerequisites..."

# Check Python virtual environment
if [[ -z "$VIRTUAL_ENV" ]]; then
    if [[ -f "venv/bin/activate" ]]; then
        log_info "Activating virtual environment..."
        source venv/bin/activate
    else
        log_warn "No virtual environment found. Using system Python."
    fi
fi

# Check if API is running
API_HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null || echo "")
if [[ -z "$API_HEALTH" ]]; then
    log_warn "NovaSurge API not running on :8000"
    log_info "Start it with: cd novasurge && python -m api.main"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    log_success "NovaSurge API is running"
fi

# Check if Dashboard is running
DASH_HEALTH=$(curl -s http://localhost:5173 2>/dev/null | head -1 || echo "")
if [[ -z "$DASH_HEALTH" ]]; then
    log_warn "Dashboard not running on :5173"
    log_info "Start it with: cd dashboard && npm run dev"
else
    log_success "Dashboard is running"
fi

echo ""
log_highlight "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_highlight "                    DEMO STRUCTURE (7 Minutes)                      "
log_highlight "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "  ${CYAN}Minute 1:${NC}  Introduction and dashboard overview"
echo -e "  ${CYAN}Minute 2-3:${NC} Round 1 — Pod Deletion on Order Service"
echo -e "  ${CYAN}Minute 4:${NC}    Show dependency graph blast radius"
echo -e "  ${CYAN}Minute 5-6:${NC} Rounds 2-3 — CPU Throttle, Network Partition"
echo -e "  ${CYAN}Minute 7:${NC}    Summary — All 5 rounds in decision trace"
echo ""
log_highlight "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Demo rounds overview
echo ""
log_info "Chaos Rounds Overview:"
echo ""
printf "  %-4s %-22s %-20s %s\n" "RND" "FAILURE TYPE" "TARGET SERVICE" "REMEDIATION"
echo "  ─────────────────────────────────────────────────────────────────────"
printf "  ${GREEN}%-4s${NC} %-22s %-20s %s\n" "1" "Pod Deletion" "order-service" "pod_restart → hpa_scaleout"
printf "  ${GREEN}%-4s${NC} %-22s %-20s %s\n" "2" "CPU Throttle" "payment-service" "hpa_scaleout → cache_flush"
printf "  ${GREEN}%-4s${NC} %-22s %-20s %s\n" "3" "Network Partition" "product-service" "traffic_reroute → pod_restart"
printf "  ${GREEN}%-4s${NC} %-22s %-20s %s\n" "4" "Latency Injection" "order-service" "cache_flush → hpa_scaleout"
printf "  ${GREEN}%-4s${NC} %-22s %-20s %s\n" "5" "Replica Reduction" "payment-service" "hpa_scaleout → traffic_reroute"
echo ""

# Opening statement
echo ""
log_header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_header "                     OPENING STATEMENT                              "
log_header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "  ${CYAN}NovaSurge is an autonomous chaos engineering system that not only${NC}"
echo -e "  ${CYAN}breaks microservices intentionally but detects, explains, and heals${NC}"
echo -e "  ${CYAN}them in real time — while narrating its reasoning live.${NC}"
echo ""
echo -e "  ${YELLOW}Key Differentiators:${NC}"
echo -e "    • Autonomous reasoning feed — no LLM, fully offline"
echo -e "    • Root cause analysis via service dependency graph"
echo -e "    • Intelligent failure strategy — targets highest blast radius"
echo -e "    • SLA-aware remediation — payment path prioritized"
echo -e "    • 4-layer safety guardrails prevent cascade failures"
echo ""

# Wait for user to be ready
echo ""
read -p "Press Enter when ready to begin the demo..."
echo ""

# Pre-flight checks
log_info "Running pre-flight checks..."

# Check ML models exist
if [[ ! -f "novasurge/models/iforest.pkl" ]]; then
    log_warn "ML models not found. Training now..."
    cd novasurge
    python -m ml.generate_synthetic
    python -m ml.train_iforest
    python -m ml.train_lstm 2>/dev/null || log_warn "LSTM training skipped"
    cd ..
else
    log_success "ML models found"
fi

# Check if Kubernetes is accessible
if command -v kubectl &> /dev/null; then
    KUBECTL_CHECK=$(kubectl get pods -n shopfusion 2>/dev/null | wc -l || echo "0")
    if [[ "$KUBECTL_CHECK" -gt 0 ]]; then
        log_success "Kubernetes cluster accessible"
        echo ""
        log_info "Current cluster status:"
        kubectl get pods -n shopfusion 2>/dev/null | head -10 || echo "  (No pods found or namespace doesn't exist)"
    else
        log_warn "Kubernetes not accessible — will use mock mode"
    fi
else
    log_warn "kubectl not found — will use mock mode"
fi

echo ""
log_highlight "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_highlight "                    STARTING 5-ROUND DEMO                           "
log_highlight "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Run the orchestrator
cd novasurge

log_info "Starting orchestrator..."
echo ""
echo -e "  ${YELLOW}Note:${NC} Each round includes:"
echo -e "    1. Pre-flight blast radius check"
echo -e "    2. Chaos injection"
echo -e "    3. Anomaly detection (ML inference)"
echo -e "    4. Root cause analysis"
echo -e "    5. Guardrail evaluation"
echo -e "    6. Remediation execution"
echo -e "    7. Health verification"
echo -e "    8. Metric normalization wait"
echo ""

# Set environment for colored output
export PYTHONUNBUFFERED=1

if [[ -n "$DRY_RUN" ]]; then
    python -m orchestrator --dry-run
else
    python -m orchestrator
fi

ORCHESTRATOR_EXIT=$?

cd "$PROJECT_ROOT"

echo ""
log_highlight "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_highlight "                      DEMO COMPLETE                                 "
log_highlight "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [[ $ORCHESTRATOR_EXIT -eq 0 ]]; then
    log_success "All rounds completed successfully!"
else
    log_warn "Orchestrator exited with code $ORCHESTRATOR_EXIT"
fi

# Show summary if logs exist
if [[ -f "novasurge/logs/all_rounds_summary.json" ]]; then
    echo ""
    log_info "Summary available at: novasurge/logs/all_rounds_summary.json"
    echo ""
    echo "  Preview:"
    cat novasurge/logs/all_rounds_summary.json | python -m json.tool 2>/dev/null | head -30 || cat novasurge/logs/all_rounds_summary.json | head -30
fi

# Closing statement
echo ""
log_header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_header "                     CLOSING STATEMENT                              "
log_header "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "  ${CYAN}The infrastructure for resilience exists everywhere.${NC}"
echo -e "  ${CYAN}The intelligence layer is what we built.${NC}"
echo ""
echo -e "  ${GREEN}NovaSurge demonstrates:${NC}"
echo -e "    ✓ Autonomous detection and classification of failures"
echo -e "    ✓ Root cause analysis before remediation"
echo -e "    ✓ Safety guardrails preventing cascade failures"
echo -e "    ✓ SLA-aware prioritization of critical services"
echo -e "    ✓ Complete audit trail with natural language reasoning"
echo ""
echo -e "  ${YELLOW}Thank you for evaluating NovaSurge!${NC}"
echo ""

# Show useful commands
echo ""
log_info "Useful commands:"
echo ""
echo "  View API docs:     curl http://localhost:8000/"
echo "  Current anomaly:   curl http://localhost:8000/anomaly/current"
echo "  Round history:     curl http://localhost:8000/rounds"
echo "  Check K8s pods:    kubectl get pods -n shopfusion"
echo "  View logs:         tail -f novasurge/logs/round_*.json"
echo "  Clean up:          make clean"
echo ""
