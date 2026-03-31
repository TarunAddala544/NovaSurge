#!/usr/bin/env python3
"""
NovaSurge - Synthetic Data Generator
Generates realistic baseline metrics with controlled anomalies for training.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

# Service definitions with realistic healthy ranges
SERVICE_PROFILES = {
    "api-gateway": {
        "http_request_rate": (45, 55),
        "error_rate": (0.001, 0.01),
        "p99_latency": (50, 150),
        "cpu_usage": (0.1, 0.3),
        "memory_usage": (100, 200),
        "active_connections": (20, 40),
    },
    "product-service": {
        "http_request_rate": (30, 40),
        "error_rate": (0.001, 0.005),
        "p99_latency": (30, 80),
        "cpu_usage": (0.05, 0.2),
        "memory_usage": (150, 250),
        "active_connections": (15, 25),
    },
    "order-service": {
        "http_request_rate": (10, 20),
        "error_rate": (0.005, 0.02),
        "p99_latency": (100, 300),
        "cpu_usage": (0.1, 0.35),
        "memory_usage": (120, 220),
        "active_connections": (5, 15),
    },
    "payment-service": {
        "http_request_rate": (8, 15),
        "error_rate": (0.01, 0.05),
        "p99_latency": (150, 400),
        "cpu_usage": (0.1, 0.3),
        "memory_usage": (100, 180),
        "active_connections": (3, 10),
    },
    "notification-service": {
        "http_request_rate": (5, 10),
        "error_rate": (0.001, 0.003),
        "p99_latency": (20, 50),
        "cpu_usage": (0.02, 0.1),
        "memory_usage": (80, 120),
        "active_connections": (2, 5),
    },
}


def generate_baseline_value(min_val, max_val, noise_factor=0.05):
    """Generate a value with random noise."""
    base = np.random.uniform(min_val, max_val)
    noise = np.random.normal(0, (max_val - min_val) * noise_factor)
    return max(0, base + noise)


def inject_anomaly_pattern(service_profile, anomaly_type):
    """Inject specific anomaly patterns into metrics."""
    metrics = {}

    for metric, (min_val, max_val) in service_profile.items():
        base = np.random.uniform(min_val, max_val)

        if anomaly_type == "high_latency":
            if metric == "p99_latency":
                base = base * np.random.uniform(5, 10)
            elif metric == "error_rate":
                base = base * np.random.uniform(0.8, 1.2)  # Near baseline
            elif metric == "active_connections":
                base = base * np.random.uniform(0.9, 1.1)

        elif anomaly_type == "error_spike":
            if metric == "error_rate":
                base = base * np.random.uniform(10, 20)
            elif metric == "p99_latency":
                base = base * np.random.uniform(1.1, 1.5)

        elif anomaly_type == "cpu_throttle":
            if metric == "cpu_usage":
                base = min(1.0, base * np.random.uniform(5, 8))
            elif metric == "http_request_rate":
                base = base * np.random.uniform(0.9, 1.1)

        elif anomaly_type == "network_partition":
            if metric == "http_request_rate":
                base = base * np.random.uniform(0.01, 0.1)
            elif metric == "active_connections":
                base = base * np.random.uniform(0.0, 0.2)
            elif metric == "error_rate":
                base = base * np.random.uniform(5, 10)

        elif anomaly_type == "replica_exhaustion":
            if metric in ["http_request_rate", "cpu_usage", "memory_usage", "active_connections"]:
                base = base * np.random.uniform(0.1, 0.3)

        elif anomaly_type == "cache_miss_spike":
            if metric == "error_rate":
                base = base * np.random.uniform(3, 6)
            elif metric == "p99_latency":
                base = base * np.random.uniform(2, 4)
            elif metric == "http_request_rate":
                base = base * np.random.uniform(0.8, 1.0)

        elif anomaly_type == "pod_crash":
            if metric == "error_rate":
                base = base * np.random.uniform(15, 30)
            elif metric == "active_connections":
                base = base * np.random.uniform(0.0, 0.1)

        metrics[metric] = max(0, base)

    return metrics


def generate_synthetic_data(
    n_baseline=1500,
    n_anomalies=75,
    contamination=0.05,
    output_path="novasurge/data/synthetic_baseline.csv",
):
    """Generate synthetic data with healthy baseline and anomalies."""

    print(f"Generating {n_baseline} baseline samples + {n_anomalies} anomaly samples...")
    print(f"Total contamination: {n_anomalies / (n_baseline + n_anomalies):.2%}")

    services = list(SERVICE_PROFILES.keys())
    rows = []
    start_time = datetime.now() - timedelta(hours=4)

    # Generate baseline data
    for i in range(n_baseline):
        for service in services:
            profile = SERVICE_PROFILES[service]
            row = {
                "timestamp": start_time + timedelta(seconds=i * 10),
                "service": service,
            }
            for metric, (min_val, max_val) in profile.items():
                row[metric] = generate_baseline_value(min_val, max_val)
            rows.append(row)

    # Inject anomalies
    anomaly_types = [
        "high_latency", "error_spike", "cpu_throttle",
        "network_partition", "replica_exhaustion", "cache_miss_spike", "pod_crash"
    ]

    for i in range(n_anomalies):
        service = np.random.choice(services)
        anomaly_type = np.random.choice(anomaly_types)
        profile = SERVICE_PROFILES[service]

        row = {
            "timestamp": start_time + timedelta(seconds=(n_baseline + i) * 10),
            "service": service,
        }

        anomalous_metrics = inject_anomaly_pattern(profile, anomaly_type)
        row.update(anomalous_metrics)
        rows.append(row)

    # Create DataFrame
    df = pd.DataFrame(rows)

    # Ensure correct column order
    column_order = [
        "timestamp", "service", "http_request_rate", "error_rate",
        "p99_latency", "cpu_usage", "memory_usage", "active_connections"
    ]
    df = df[column_order]

    # Sort by timestamp
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Save to CSV
    df.to_csv(output_path, index=False)

    # Print summary
    print(f"\n✅ Synthetic data generated successfully!")
    print(f"   File: {os.path.abspath(output_path)}")
    print(f"   Total rows: {len(df)}")
    print(f"   Services: {df['service'].nunique()}")
    print(f"   Time range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    # Show statistics
    print("\n📊 Metric Statistics by Service:")
    for service in services:
        service_df = df[df["service"] == service]
        print(f"\n{service}:")
        print(f"  http_request_rate: {service_df['http_request_rate'].mean():.1f} ± {service_df['http_request_rate'].std():.1f}")
        print(f"  error_rate: {service_df['error_rate'].mean():.4f} ± {service_df['error_rate'].std():.4f}")
        print(f"  p99_latency: {service_df['p99_latency'].mean():.1f} ± {service_df['p99_latency'].std():.1f}")

    return df


if __name__ == "__main__":
    df = generate_synthetic_data()
    print(f"\n🚀 Ready for training!")
