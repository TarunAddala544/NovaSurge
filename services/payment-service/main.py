import os
import json
import time
import random
import logging
import asyncio
from contextlib import asynccontextmanager

import redis as redis_lib
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from prometheus_client import (
    Counter, Histogram, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
)

import database
import models

# ── Logging ──────────────────────────────────────────────────────────────────
SERVICE_NAME = "payment-service"


class JSONFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f"),
            "service": SERVICE_NAME,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra"):
            entry.update(record.extra)
        return json.dumps(entry)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger(SERVICE_NAME)
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.propagate = False


def log(level, message, **kwargs):
    py_level = "WARNING" if level == "WARN" else level
    record = logger.makeRecord(SERVICE_NAME, getattr(logging, py_level), "", 0, message, (), None)
    record.extra = kwargs
    logger.handle(record)


# ── Prometheus ────────────────────────────────────────────────────────────────
registry = CollectorRegistry()

http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests",
    ["method", "endpoint", "status_code"], registry=registry,
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration",
    ["method", "endpoint", "status_code"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
    registry=registry,
)
service_errors_total = Counter(
    "service_errors_total", "Total service errors",
    ["method", "endpoint"], registry=registry,
)
active_connections = Gauge(
    "active_connections", "Active connections", registry=registry,
)

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "redis-service")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app_instance):
    database.Base.metadata.create_all(bind=database.engine)
    yield


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="payment-service", lifespan=lifespan)


# ── Middleware ────────────────────────────────────────────────────────────────
@app.middleware("http")
async def instrumentation(request: Request, call_next):
    active_connections.inc()
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    labels = {
        "method": request.method,
        "endpoint": request.url.path,
        "status_code": str(response.status_code),
    }
    http_requests_total.labels(**labels).inc()
    http_request_duration_seconds.labels(**labels).observe(duration)
    if response.status_code >= 500:
        service_errors_total.labels(method=request.method, endpoint=request.url.path).inc()
    active_connections.dec()
    log(
        "ERROR" if response.status_code >= 400 else "INFO",
        "request completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2),
    )
    return response


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@app.post("/payments", response_model=models.PaymentResponse, status_code=201)
async def create_payment(payload: models.PaymentCreate, db: Session = Depends(database.get_db)):
    payment = models.PaymentORM(
        order_id=payload.order_id,
        amount=payload.amount,
        status="processing",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # Simulate 200ms processing delay
    await asyncio.sleep(0.2)

    # 95% success rate
    payment.status = "success" if random.random() < 0.95 else "failed"
    db.commit()
    db.refresh(payment)

    # Publish to Redis payment-events channel
    try:
        event = {
            "payment_id": payment.id,
            "order_id": payment.order_id,
            "status": payment.status,
        }
        redis_client.publish("payment-events", json.dumps(event))
        log("INFO", "payment event published", **event)
    except Exception as e:
        log("WARN", "redis publish failed", error=str(e))

    return payment


@app.get("/payments/{payment_id}", response_model=models.PaymentResponse)
def get_payment(payment_id: int, db: Session = Depends(database.get_db)):
    payment = db.query(models.PaymentORM).filter(models.PaymentORM.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment
