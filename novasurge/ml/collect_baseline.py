#!/usr/bin/env python3
"""
NovaSurge - Baseline Collector
Collects live metrics from Prometheus for 20 minutes.
"""

import time
import csv
import os
from datetime import datetime, timedelta

from prometheus_fetcher import fetch_metrics_snapshot_sync, SERVICES


def collect_baseline(
    duration_minutes: int = 20,
    interval_seconds: int = 10,
    output_path: str = "novasurge/data/live_baseline.csv",
):
    """
    Collect baseline metrics from Prometheus.

    Args:
        duration_minutes: How long to collect (default 20 min)
        interval_seconds: Interval between samples (default 10 sec)
        output_path: Where to save the CSV
    """
    print(f"🚀 Starting baseline collection")
    print(f"   Duration: {duration_minutes} minutes")
    print(f"   Interval: {interval_seconds} seconds")
    print(f"   Expected samples: ~{duration_minutes * 60 // interval_seconds * len(SERVICES)}")
    print(f"   Output: {output_path}\n")

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # CSV columns
    fieldnames = [
        "timestamp", "service", "http_request_rate", "error_rate",
        "p99_latency", "cpu_usage", "memory_usage", "active_connections"
    ]

    # Track start time
    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=duration_minutes)

    rows_collected = 0
    last_minute_reported = -1

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        while datetime.now() < end_time:
            loop_start = time.time()

            # Fetch metrics
            metrics = fetch_metrics_snapshot_sync()

            # Check if we got real data
            using_fallback = metrics.pop("_staleness_warning", False)
            if using_fallback:
                print("⚠️  Warning: Prometheus unavailable, using fallback data")

            timestamp = datetime.now().isoformat()

            # Write each service's metrics
            for service in SERVICES:
                if service not in metrics:
                    continue

                service_metrics = metrics[service]
                row = {
                    "timestamp": timestamp,
                    "service": service,
                    "http_request_rate": service_metrics.get("http_request_rate", 0),
                    "error_rate": service_metrics.get("error_rate", 0),
                    "p99_latency": service_metrics.get("p99_latency", 0),
                    "cpu_usage": service_metrics.get("cpu_usage", 0),
                    "memory_usage": service_metrics.get("memory_usage", 0),
                    "active_connections": service_metrics.get("active_connections", 0),
                }
                writer.writerow(row)
                rows_collected += 1

            # Report progress every minute
            elapsed = datetime.now() - start_time
            elapsed_minutes = int(elapsed.total_seconds() // 60)

            if elapsed_minutes != last_minute_reported:
                last_minute_reported = elapsed_minutes
                remaining = end_time - datetime.now()
                print(f"⏱️  Minute {elapsed_minutes}/{duration_minutes}: {rows_collected} rows collected, {max(0, remaining.seconds // 60)} min remaining")

            # Sleep until next interval
            elapsed_loop = time.time() - loop_start
            sleep_time = max(0, interval_seconds - elapsed_loop)
            time.sleep(sleep_time)

    print(f"\n✅ Baseline collection complete!")
    print(f"   Total rows collected: {rows_collected}")
    print(f"   File: {os.path.abspath(output_path)}")
    print(f"\n🚀 Ready to train!")

    return rows_collected


if __name__ == "__main__":
    # Allow quick test with shorter duration
    import sys

    duration = 20  # default 20 minutes
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [duration_minutes]")
            sys.exit(1)

    collect_baseline(duration_minutes=duration)
