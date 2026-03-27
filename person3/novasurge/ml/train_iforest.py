#!/usr/bin/env python3
"""
NovaSurge - Isolation Forest Trainer
Trains an Isolation Forest model for anomaly detection.
"""

import pandas as pd
import numpy as np
import pickle
import os
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


def train_iforest(
    data_path="novasurge/data/synthetic_baseline.csv",
    model_path="novasurge/models/iforest.pkl",
    scaler_path="novasurge/models/scaler.pkl",
    contamination=0.05,
):
    """Train Isolation Forest on baseline data."""

    print(f"Loading data from {data_path}...")
    df = pd.read_csv(data_path)

    # Feature columns in exact order
    feature_cols = [
        "http_request_rate",
        "error_rate",
        "p99_latency",
        "cpu_usage",
        "memory_usage",
        "active_connections",
    ]

    print(f"Training on {len(df)} samples...")
    print(f"Features: {feature_cols}")
    print(f"Contamination: {contamination}")

    # Prepare features
    X = df[feature_cols].values

    # Scale features
    print("\nFitting StandardScaler...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train Isolation Forest
    print("Training Isolation Forest...")
    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=42,
        max_features=1.0,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    # Evaluate on training data
    scores = model.decision_function(X_scaled)
    predictions = model.predict(X_scaled)

    # Print statistics
    print("\n📊 Training Summary:")
    print(f"  Average anomaly score: {np.mean(scores):.4f}")
    print(f"  Score std: {np.std(scores):.4f}")
    print(f"  Min score: {np.min(scores):.4f}")
    print(f"  Max score: {np.max(scores):.4f}")
    print(f"  Anomalies detected: {np.sum(predictions == -1)} ({100 * np.sum(predictions == -1) / len(predictions):.2f}%)")
    print(f"  Contamination setting: {contamination:.2%}")

    # Save model and scaler
    os.makedirs(os.path.dirname(model_path), exist_ok=True)

    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    print(f"\n✅ Model saved to: {os.path.abspath(model_path)}")

    with open(scaler_path, "wb") as f:
        pickle.dump(scaler, f)
    print(f"✅ Scaler saved to: {os.path.abspath(scaler_path)}")

    # Save feature stats for reference
    stats = {
        "feature_names": feature_cols,
        "feature_means": X.mean(axis=0).tolist(),
        "feature_stds": X.std(axis=0).tolist(),
    }

    stats_path = model_path.replace(".pkl", "_stats.json")
    import json

    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"✅ Feature stats saved to: {os.path.abspath(stats_path)}")
    print("\n🚀 Isolation Forest training complete!")

    return model, scaler


if __name__ == "__main__":
    model, scaler = train_iforest()
