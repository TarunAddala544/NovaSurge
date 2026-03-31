#!/usr/bin/env python3
"""
NovaSurge - FastAPI Backend
WebSocket streaming and REST endpoints for anomaly detection.
"""

import json
import os
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ml"))

from inference import (
    load_models,
    run_inference_step,
    get_current_anomaly,
    get_current_metrics,
    get_anomaly_history,
    SERVICES,
)

# State paths
STATE_DIR = "novasurge/state"
DATA_DIR = "novasurge/data"
LOGS_DIR = "novasurge/logs"

# Ensure directories exist
for d in [STATE_DIR, DATA_DIR, LOGS_DIR]:
    os.makedirs(d, exist_ok=True)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"🔗 WebSocket client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"🔌 WebSocket client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()

# File watchers for state changes
_last_round_status: Optional[dict] = None
_last_reasoning: Optional[str] = None


def read_round_status() -> Optional[dict]:
    """Read round status from Person 2's orchestrator."""
    try:
        path = f"{STATE_DIR}/round_status.json"
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        pass
    return None


def read_reasoning_log() -> Optional[str]:
    """Read latest reasoning from Person 4's engine."""
    try:
        path = f"{DATA_DIR}/reasoning_log.jsonl"
        if os.path.exists(path):
            with open(path, "r") as f:
                lines = f.readlines()
                if lines:
                    last_line = lines[-1].strip()
                    data = json.loads(last_line)
                    return data.get("reasoning", "")
    except Exception as e:
        pass
    return None


def read_rounds() -> List[dict]:
    """Read round summaries from logs."""
    rounds = []
    try:
        for filename in os.listdir(LOGS_DIR):
            if filename.startswith("round_") and filename.endswith(".json"):
                path = os.path.join(LOGS_DIR, filename)
                with open(path, "r") as f:
                    rounds.append(json.load(f))
        rounds.sort(key=lambda x: x.get("round_number", 0))
    except Exception:
        pass
    return rounds


def build_dependency_graph(metrics: dict, scores: dict) -> dict:
    """Build dependency graph for visualization."""
    # Define service dependencies
    dependencies = {
        "api-gateway": ["product-service", "order-service"],
        "product-service": [],
        "order-service": ["payment-service", "notification-service"],
        "payment-service": [],
        "notification-service": [],
    }

    nodes = []
    edges = []

    for service in SERVICES:
        service_metrics = metrics.get(service, {})
        score = scores.get(service, 0)

        # Determine health based on score
        if score < -0.15:
            health = "anomaly"
        elif score < -0.05:
            health = "degraded"
        else:
            health = "healthy"

        nodes.append({
            "id": service,
            "health": health,
            "score": round(score, 4),
            "request_rate": service_metrics.get("http_request_rate", 0),
        })

        # Add edges
        for target in dependencies.get(service, []):
            edges.append({
                "source": service,
                "target": target,
                "weight": 1.0,  # Could be computed from actual traffic
            })

    return {"nodes": nodes, "edges": edges}


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    print("🚀 Starting NovaSurge API...")
    if load_models():
        print("✅ Models loaded successfully")
    else:
        print("⚠️  Failed to load models, some features may be unavailable")

    # Start background broadcaster
    asyncio.create_task(broadcast_loop())
    print("✅ WebSocket broadcaster started")

    yield

    # Shutdown
    print("👋 Shutting down NovaSurge API...")


app = FastAPI(
    title="NovaSurge Anomaly Detection API",
    description="ML-powered anomaly detection and chaos engineering platform",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def broadcast_loop():
    """Background task to broadcast data every 5 seconds."""
    global _last_round_status, _last_reasoning

    while True:
        try:
            # Run inference step
            result = run_inference_step()
            if result is None:
                await asyncio.sleep(5.0)
                continue
            anomaly, metrics, scores, lstm_results = result

            # Get current timestamp
            timestamp = datetime.now().isoformat()

            # Read round status
            round_status = read_round_status() or {
                "current_round": 0,
                "phase": "IDLE",
                "elapsed_seconds": 0,
                "failure_type": None,
            }

            # Read latest reasoning
            reasoning = read_reasoning_log()

            # Build dependency graph
            dependency_graph = build_dependency_graph(metrics, scores)

            # Build WebSocket message
            message = {
                "timestamp": timestamp,
                "scores": {s: round(scores.get(s, 0), 4) for s in SERVICES},
                "anomaly": anomaly if anomaly.get("anomaly_detected") else None,
                "reasoning": reasoning,
                "metrics_snapshot": metrics,
                "lstm_predictions": lstm_results,
                "round_status": round_status,
                "dependency_graph": dependency_graph,
            }

            # Broadcast to all clients
            await manager.broadcast(message)

        except Exception as e:
            print(f"Error in broadcast loop: {e}")

        await asyncio.sleep(5.0)


@app.get("/")
async def root():
    """API status."""
    return {
        "status": "healthy",
        "service": "NovaSurge Anomaly Detection API",
        "version": "1.0.0",
    }


@app.get("/anomaly/current")
async def get_anomaly():
    """Get current anomaly status."""
    return get_current_anomaly()


@app.get("/anomaly/history")
async def get_history(limit: int = 100):
    """Get anomaly history."""
    return get_anomaly_history(limit)


@app.get("/rounds")
async def get_rounds():
    """Get round summaries."""
    return read_rounds()


@app.get("/metrics/current")
async def get_metrics():
    """Get current metrics for all services."""
    return get_current_metrics()


@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time streaming."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_text()
            # Echo back for ping/pong
            await websocket.send_text(f"ack: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

@app.get("/health")
async def health():
    return {"status": "ok", "platform": "novasurge"}
