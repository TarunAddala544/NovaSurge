#!/usr/bin/env python3
"""
NovaSurge - Inference Engine
Continuously runs anomaly detection using Isolation Forest and LSTM.
"""

import json
import os
import pickle
import time
from datetime import datetime
from collections import deque
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from prometheus_fetcher import fetch_metrics_snapshot_sync, SERVICES

# State paths
STATE_DIR = "novasurge/state"
DATA_DIR = "novasurge/data"
MODELS_DIR = "novasurge/models"

# Feature columns (must match training order)
FEATURE_COLS = [
    "http_request_rate",
    "error_rate",
    "p99_latency",
    "cpu_usage",
    "memory_usage",
    "active_connections",
]

# Rolling buffer for LSTM (seq_length=10)
SEQUENCE_LENGTH = 10
service_buffers: Dict[str, deque] = {s: deque(maxlen=SEQUENCE_LENGTH) for s in SERVICES}

# Baseline stats for feature delta calculation
_baseline_stats = {}

# Current anomaly state
_current_anomaly = {
    "anomaly_detected": False,
    "affected_service": None,
    "anomaly_type": None,
    "severity_score": 0.0,
    "iforest_score": 0.0,
    "lstm_reconstruction_error": 0.0,
    "feature_deltas": {},
    "detected_at": None,
}

# Load models (will be loaded on first run)
_iforest_model = None
_scaler = None
_lstm_model = None
_lstm_threshold = None
_lstm_available = False


def load_models():
    """Load all ML models."""
    global _iforest_model, _scaler, _lstm_model, _lstm_threshold, _lstm_available

    # Load Isolation Forest
    try:
        with open(f"{MODELS_DIR}/iforest.pkl", "rb") as f:
            _iforest_model = pickle.load(f)
        with open(f"{MODELS_DIR}/scaler.pkl", "rb") as f:
            _scaler = pickle.load(f)
        print("✅ Isolation Forest model loaded")
    except Exception as e:
        print(f"❌ Failed to load Isolation Forest: {e}")
        return False

    # Load baseline stats
    try:
        with open(f"{MODELS_DIR}/iforest_stats.json", "r") as f:
            stats = json.load(f)
            global _baseline_stats
            _baseline_stats = dict(zip(stats["feature_names"], zip(stats["feature_means"], stats["feature_stds"])))
    except Exception as e:
        print(f"⚠️  Could not load baseline stats: {e}")
        # Compute from training data
        df = pd.read_csv(f"{DATA_DIR}/synthetic_baseline.csv")
        for col in FEATURE_COLS:
            _baseline_stats[col] = (df[col].mean(), df[col].std())

    # Try to load LSTM (may fail if torch not available)
    try:
        import torch
        from train_lstm import LSTMAutoencoder

        checkpoint = torch.load(f"{MODELS_DIR}/lstm.pt", map_location="cpu")
        config = checkpoint["config"]

        _lstm_model = LSTMAutoencoder(
            input_size=config["input_size"],
            hidden_size=config["hidden_size"],
            num_layers=config["num_layers"],
        )
        _lstm_model.load_state_dict(checkpoint["model_state_dict"])
        _lstm_model.eval()

        with open(f"{MODELS_DIR}/lstm_threshold.json", "r") as f:
            _lstm_threshold = json.load(f)

        _lstm_available = True
        print("✅ LSTM model loaded")
    except Exception as e:
        print(f"⚠️  LSTM not available: {e}")
        _lstm_available = False

    return True


def classify_anomaly_type(service: str, metrics: Dict[str, float]) -> str:
    """Classify the type of anomaly based on metric patterns."""
    # Get baseline means
    error_rate_mean = _baseline_stats.get("error_rate", (0.01, 0.01))[0]
    latency_mean = _baseline_stats.get("p99_latency", (100, 50))[0]
    cpu_mean = _baseline_stats.get("cpu_usage", (0.2, 0.1))[0]
    connections_mean = _baseline_stats.get("active_connections", (10, 5))[0]
    request_rate_mean = _baseline_stats.get("http_request_rate", (20, 10))[0]

    error_rate = metrics.get("error_rate", 0)
    latency = metrics.get("p99_latency", 0)
    cpu = metrics.get("cpu_usage", 0)
    connections = metrics.get("active_connections", 0)
    request_rate = metrics.get("http_request_rate", 0)

    # Classification rules
    if error_rate > 10 * error_rate_mean and connections < 0.2 * connections_mean:
        return "pod_crash"
    elif cpu > 5 * cpu_mean and request_rate > 0.8 * request_rate_mean:
        return "cpu_throttle"
    elif request_rate < 0.1 * request_rate_mean and connections < 0.2 * connections_mean:
        return "network_partition"
    elif latency > 5 * latency_mean and error_rate < 2 * error_rate_mean:
        return "high_latency"
    elif all(metrics.get(m, 1) < 0.3 * _baseline_stats.get(m, (1, 0))[0] for m in ["http_request_rate", "cpu_usage", "memory_usage"]):
        return "replica_exhaustion"
    elif request_rate > 0.8 * request_rate_mean and error_rate > 3 * error_rate_mean and service == "product-service":
        return "cache_miss_spike"
    else:
        return "unknown"


def compute_feature_deltas(metrics: Dict[str, float]) -> Dict[str, float]:
    """Compute feature deltas from baseline."""
    deltas = {}
    for feature in FEATURE_COLS:
        if feature in metrics and feature in _baseline_stats:
            current = metrics[feature]
            mean, std = _baseline_stats[feature]
            if std > 0:
                deltas[feature] = (current - mean) / std
            else:
                deltas[feature] = 0.0
    return deltas


def run_inference_step():
    """Run one inference step."""
    global _current_anomaly

    if _iforest_model is None or _scaler is None:
        print("Models not loaded, skipping inference")
        return

    # Step 1: Fetch metrics
    metrics_snapshot = fetch_metrics_snapshot_sync()

    # Check if using synthetic/fallback data
    using_fallback = metrics_snapshot.pop("_staleness_warning", False)

    # Step 2 & 3: Run inference for each service
    anomaly_detected = False
    affected_service = None
    max_severity = 0.0
    iforest_scores = {}
    lstm_results = {}

    for service in SERVICES:
        if service not in metrics_snapshot:
            continue

        service_metrics = metrics_snapshot[service]
        features = np.array([[service_metrics.get(f, 0) for f in FEATURE_COLS]])

        # Scale features
        features_scaled = _scaler.transform(features)

        # Isolation Forest
        iforest_score = _iforest_model.decision_function(features_scaled)[0]
        iforest_anomaly = iforest_score < -0.15
        iforest_scores[service] = iforest_score

        # LSTM (if available)
        lstm_anomaly = False
        lstm_error = 0.0
        predicted_score = 0.0
        confidence = 0.0

        if _lstm_available:
            # Add to buffer
            service_buffers[service].append(features_scaled[0])

            if len(service_buffers[service]) == SEQUENCE_LENGTH:
                try:
                    import torch

                    seq = np.array(list(service_buffers[service]))
                    seq_tensor = torch.FloatTensor(seq).unsqueeze(0)  # (1, seq_len, features)

                    with torch.no_grad():
                        reconstructed = _lstm_model(seq_tensor)
                        lstm_error = torch.mean((reconstructed - seq_tensor) ** 2).item()

                    threshold = _lstm_threshold["threshold"]
                    lstm_anomaly = lstm_error > threshold

                    # Predict next score based on trend
                    if len(iforest_scores) > 1:
                        predicted_score = iforest_score + (iforest_score - iforest_scores.get(service, iforest_score)) * 0.5
                    else:
                        predicted_score = iforest_score

                    confidence = min(1.0, abs(lstm_error - threshold) / threshold)
                except Exception as e:
                    pass

        lstm_results[service] = {
            "reconstruction_error": lstm_error,
            "predicted_score_60s": predicted_score if _lstm_available else 0.0,
            "predicted_anomaly": lstm_anomaly if _lstm_available else False,
            "confidence": confidence if _lstm_available else 0.0,
        }

        # Determine if anomaly
        is_anomaly = iforest_anomaly or lstm_anomaly

        if is_anomaly:
            # Compute severity
            severity = min(1.0, abs(iforest_score) + (lstm_error / max(_lstm_threshold["threshold"], 0.001) if _lstm_available else 0))

            if severity > max_severity:
                max_severity = severity
                anomaly_detected = True
                affected_service = service

                # Classify anomaly type
                anomaly_type = classify_anomaly_type(service, service_metrics)

                # Compute feature deltas
                feature_deltas = compute_feature_deltas(service_metrics)

                # Update current anomaly
                _current_anomaly = {
                    "anomaly_detected": True,
                    "affected_service": service,
                    "anomaly_type": anomaly_type,
                    "severity_score": round(severity, 4),
                    "iforest_score": round(iforest_score, 4),
                    "lstm_reconstruction_error": round(lstm_error, 6) if _lstm_available else 0.0,
                    "feature_deltas": {k: round(v, 4) for k, v in feature_deltas.items()},
                    "detected_at": datetime.now().isoformat(),
                }

    # If no anomaly detected, clear current
    if not anomaly_detected:
        _current_anomaly = {
            "anomaly_detected": False,
            "affected_service": None,
            "anomaly_type": None,
            "severity_score": 0.0,
            "iforest_score": 0.0,
            "lstm_reconstruction_error": 0.0,
            "feature_deltas": {},
            "detected_at": None,
        }
    else:
        # Log to anomaly_log.csv
        _log_anomaly(_current_anomaly)

    # Save current metrics and anomaly state
    _save_state(metrics_snapshot, iforest_scores, lstm_results)

    return _current_anomaly, metrics_snapshot, iforest_scores, lstm_results


def _log_anomaly(anomaly: Dict):
    """Log anomaly to CSV."""
    log_path = f"{DATA_DIR}/anomaly_log.csv"
    os.makedirs(DATA_DIR, exist_ok=True)

    # Create file with headers if not exists
    if not os.path.exists(log_path):
        with open(log_path, "w") as f:
            f.write("timestamp,affected_service,anomaly_type,severity_score,iforest_score,feature_deltas\n")

    # Append anomaly
    with open(log_path, "a") as f:
        feature_deltas_str = json.dumps(anomaly.get("feature_deltas", {}))
        f.write(f"{anomaly['detected_at']},{anomaly['affected_service']},{anomaly['anomaly_type']},{anomaly['severity_score']},{anomaly['iforest_score']},{feature_deltas_str}\n")


def _save_state(metrics_snapshot: Dict, iforest_scores: Dict, lstm_results: Dict):
    """Save current state to files."""
    os.makedirs(STATE_DIR, exist_ok=True)

    # Save current anomaly
    with open(f"{STATE_DIR}/current_anomaly.json", "w") as f:
        json.dump(_current_anomaly, f, indent=2)

    # Save current metrics with anomaly scores
    metrics_with_scores = {}
    for service, metrics in metrics_snapshot.items():
        metrics_with_scores[service] = {
            **metrics,
            "anomaly_score": iforest_scores.get(service, 0.0),
        }

    with open(f"{STATE_DIR}/metrics_current.json", "w") as f:
        json.dump(metrics_with_scores, f, indent=2)


def get_current_anomaly():
    """Get current anomaly state."""
    return _current_anomaly


def get_current_metrics():
    """Get current metrics snapshot."""
    try:
        with open(f"{STATE_DIR}/metrics_current.json", "r") as f:
            return json.load(f)
    except:
        return {}


def get_anomaly_history(limit: int = 100) -> List[Dict]:
    """Get anomaly history from log."""
    log_path = f"{DATA_DIR}/anomaly_log.csv"
    if not os.path.exists(log_path):
        return []

    try:
        df = pd.read_csv(log_path)
        df = df.sort_values("timestamp", ascending=False).head(limit)
        return df.to_dict(orient="records")
    except:
        return []


def inference_loop(interval: float = 10.0):
    """Main inference loop."""
    print(f"🚀 Starting inference loop (interval={interval}s)")
    print("Press Ctrl+C to stop\n")

    # Load models
    if not load_models():
        print("❌ Failed to load models, exiting")
        return

    try:
        while True:
            start_time = time.time()

            anomaly, metrics, scores, lstm = run_inference_step()

            if anomaly["anomaly_detected"]:
                print(f"\n🚨 ANOMALY DETECTED!")
                print(f"   Service: {anomaly['affected_service']}")
                print(f"   Type: {anomaly['anomaly_type']}")
                print(f"   Severity: {anomaly['severity_score']:.4f}")
                print(f"   Score: {anomaly['iforest_score']:.4f}")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No anomaly detected")

            # Sleep until next interval
            elapsed = time.time() - start_time
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n👋 Inference loop stopped")


if __name__ == "__main__":
    inference_loop()
