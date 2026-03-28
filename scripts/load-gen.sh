#!/usr/bin/env bash
# NovaSurge Load Generator
# Fires realistic traffic against the ShopFusion API to:
#   - Trigger HPA scale-up (sustained CPU load)
#   - Drive the full order flow for demo
#   - Surface chaos effects live in the terminal
#
# Usage:
#   ./scripts/load-gen.sh                          # k8s default: localhost:30080
#   ./scripts/load-gen.sh localhost:3000           # docker-compose / local dev
#   ./scripts/load-gen.sh localhost:30080 50       # 50 concurrent workers
#   ./scripts/load-gen.sh localhost:30080 20 300   # 20 workers, run for 300s
#
# Dependencies: curl, jq (optional — stats work without it)
# Install:  sudo apt-get install -y curl jq    # Ubuntu
#           brew install curl jq               # macOS

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL="http://${1:-localhost:30080}"
WORKERS="${2:-20}"          # concurrent background worker loops
DURATION="${3:-0}"          # seconds total (0 = run until Ctrl-C)
THINK_MS="${THINK_MS:-50}"  # ms pause between requests per worker (tune for load)

# Product IDs to cycle through (seeded by product-service on startup)
PRODUCT_IDS=(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20)
USER_IDS=("u1" "u2" "u3" "u4" "u5")

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ── Shared counters (temp files — bash doesn't have shared memory) ─────────────
TMPDIR_NS=$(mktemp -d /tmp/novasurge-loadgen.XXXXXX)
COUNTER_OK="${TMPDIR_NS}/ok"
COUNTER_ERR="${TMPDIR_NS}/err"
COUNTER_ORD="${TMPDIR_NS}/orders"
COUNTER_LAT="${TMPDIR_NS}/latency"   # cumulative ms (for avg)
COUNTER_REQ="${TMPDIR_NS}/reqs"      # total req count for avg

echo "0" > "$COUNTER_OK"
echo "0" > "$COUNTER_ERR"
echo "0" > "$COUNTER_ORD"
echo "0" > "$COUNTER_LAT"
echo "0" > "$COUNTER_REQ"

incr() { local f="$1" n="${2:-1}"; flock "$f" bash -c "echo \$((\$(cat '$f') + $n)) > '$f'"; }
read_counter() { cat "$1" 2>/dev/null || echo 0; }

cleanup() {
  echo -e "\n${YELLOW}Shutting down workers...${NC}"
  # Kill all background jobs in this process group
  kill 0 2>/dev/null || true
  rm -rf "$TMPDIR_NS"
  echo -e "${GREEN}Load generator stopped.${NC}"
  exit 0
}
trap cleanup SIGINT SIGTERM

# ── Pre-flight check ──────────────────────────────────────────────────────────
preflight() {
  echo -e "${BLUE}[load-gen]${NC} Checking ${BASE_URL}/health ..."
  local code
  code=$(curl -so /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/health" 2>/dev/null || echo "000")
  if [[ "$code" != "200" ]]; then
    echo -e "${RED}[FAIL]${NC} Health check returned ${code}. Is the cluster up?"
    echo "       Try: kubectl get pods -n shopfusion"
    exit 1
  fi
  echo -e "${GREEN}[OK]${NC}   Cluster healthy. Starting ${WORKERS} workers → ${BASE_URL}"
}

# ── Single request helper ─────────────────────────────────────────────────────
do_request() {
  local url="$1" method="${2:-GET}" body="${3:-}"
  local start end duration code

  start=$(date +%s%3N)

  if [[ "$method" == "POST" ]]; then
    code=$(curl -so /dev/null -w "%{http_code}" \
      --max-time 10 \
      -X POST \
      -H "Content-Type: application/json" \
      -d "$body" \
      "$url" 2>/dev/null || echo "000")
  else
    code=$(curl -so /dev/null -w "%{http_code}" \
      --max-time 10 \
      "$url" 2>/dev/null || echo "000")
  fi

  end=$(date +%s%3N)
  duration=$(( end - start ))

  if [[ "$code" =~ ^2 ]]; then
    incr "$COUNTER_OK"
  else
    incr "$COUNTER_ERR"
  fi
  incr "$COUNTER_LAT" "$duration"
  incr "$COUNTER_REQ"

  echo "$code"
}

# ── Worker loop ───────────────────────────────────────────────────────────────
worker() {
  local worker_id="$1"
  local idx=0

  while true; do
    # Rotate through: 3 GETs then 1 POST order (realistic read-heavy traffic)
    local op=$(( idx % 4 ))

    if [[ "$op" -lt 3 ]]; then
      # GET /products or GET /products/{id}
      if (( RANDOM % 2 == 0 )); then
        do_request "${BASE_URL}/products" GET > /dev/null
      else
        local pid="${PRODUCT_IDS[$(( RANDOM % ${#PRODUCT_IDS[@]} ))]}"
        do_request "${BASE_URL}/products/${pid}" GET > /dev/null
      fi
    else
      # POST /orders — full flow: stock check → payment → event
      local pid="${PRODUCT_IDS[$(( RANDOM % ${#PRODUCT_IDS[@]} ))]}"
      local uid="${USER_IDS[$(( RANDOM % ${#USER_IDS[@]} ))]}"
      local qty=$(( (RANDOM % 3) + 1 ))
      local body="{\"user_id\":\"${uid}\",\"product_id\":${pid},\"quantity\":${qty}}"
      local code
      code=$(do_request "${BASE_URL}/orders" POST "$body")
      if [[ "$code" =~ ^2 ]]; then
        incr "$COUNTER_ORD"
      fi
    fi

    idx=$(( idx + 1 ))
    sleep "0.$(printf '%03d' $THINK_MS)" 2>/dev/null || sleep 0
  done
}

# ── Stats printer ─────────────────────────────────────────────────────────────
print_stats() {
  local elapsed=0
  local last_ok=0 last_err=0 last_req=0

  while true; do
    sleep 5
    elapsed=$(( elapsed + 5 ))

    local ok err orders reqs lat
    ok=$(read_counter "$COUNTER_OK")
    err=$(read_counter "$COUNTER_ERR")
    orders=$(read_counter "$COUNTER_ORD")
    reqs=$(read_counter "$COUNTER_REQ")
    lat=$(read_counter "$COUNTER_LAT")

    local delta_ok=$(( ok - last_ok ))
    local delta_err=$(( err - last_err ))
    local delta_req=$(( reqs - last_req ))
    local rps=$(( delta_req / 5 ))
    local avg_lat=0
    [[ "$reqs" -gt 0 ]] && avg_lat=$(( lat / reqs ))

    local err_rate=0
    [[ "$(( delta_ok + delta_err ))" -gt 0 ]] && \
      err_rate=$(( delta_err * 100 / (delta_ok + delta_err) ))

    local err_color="$GREEN"
    [[ "$err_rate" -gt 5 ]]  && err_color="$YELLOW"
    [[ "$err_rate" -gt 20 ]] && err_color="$RED"

    printf "\r${BOLD}[%4ds]${NC}  " "$elapsed"
    printf "${CYAN}RPS: %3d${NC}  " "$rps"
    printf "${GREEN}2xx: %6d${NC}  " "$ok"
    printf "${err_color}err: %4d (%2d%%)${NC}  " "$err" "$err_rate"
    printf "${BLUE}orders: %5d${NC}  " "$orders"
    printf "avg: %4dms  " "$avg_lat"
    printf "workers: ${WORKERS}"

    last_ok=$ok; last_err=$err; last_req=$reqs

    # Stop if duration set and reached
    if [[ "$DURATION" -gt 0 && "$elapsed" -ge "$DURATION" ]]; then
      echo -e "\n${GREEN}Duration ${DURATION}s reached — stopping.${NC}"
      cleanup
    fi
  done
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  echo ""
  echo -e "${BOLD}${BLUE}NovaSurge Load Generator${NC}"
  echo -e "Target:   ${BASE_URL}"
  echo -e "Workers:  ${WORKERS}"
  echo -e "Duration: $([ "$DURATION" -eq 0 ] && echo 'until Ctrl-C' || echo "${DURATION}s")"
  echo -e "Think:    ${THINK_MS}ms between requests per worker"
  echo ""

  preflight

  # Spawn worker loops in background
  for i in $(seq 1 "$WORKERS"); do
    worker "$i" &
  done

  echo -e "\n${BOLD}Live stats (5s intervals) — Ctrl-C to stop${NC}\n"
  print_stats
}

main "$@"
