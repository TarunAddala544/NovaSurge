import os
import json
import time
import logging
from contextlib import asynccontextmanager

import httpx
import redis as redis_lib
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from prometheus_client import (
    Counter, Histogram, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
)

import database
import models

# ── Logging ──────────────────────────────────────────────────────────────────
SERVICE_NAME = "order-service"


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

# ── External service URLs ─────────────────────────────────────────────────────
PRODUCT_SVC = os.getenv("PRODUCT_SERVICE_URL", "http://product-service:8001")
PAYMENT_SVC = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8003")
REDIS_HOST  = os.getenv("REDIS_HOST", "redis-service")
REDIS_PORT  = int(os.getenv("REDIS_PORT", "6379"))

redis_client = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app_instance):
    database.Base.metadata.create_all(bind=database.engine)
    yield


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="order-service", lifespan=lifespan)


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


@app.post("/orders", response_model=models.OrderResponse, status_code=201)
async def create_order(payload: models.OrderCreate, db: Session = Depends(database.get_db)):
    order = models.OrderORM(
        user_id=payload.user_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        status="pending",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    async with httpx.AsyncClient(timeout=5.0) as client:
        # 1. Check product stock
        try:
            prod_resp = await client.get(f"{PRODUCT_SVC}/products/{payload.product_id}")
            if prod_resp.status_code != 200:
                order.status = "failed"
                db.commit()
                raise HTTPException(status_code=404, detail="Product not found")
            product = prod_resp.json()
            if product["stock"] < payload.quantity:
                order.status = "failed"
                db.commit()
                raise HTTPException(status_code=400, detail="Insufficient stock")
        except httpx.RequestError as e:
            order.status = "failed"
            db.commit()
            raise HTTPException(status_code=502, detail=f"Product service unavailable: {e}")

        # 2. Initiate payment
        try:
            pay_resp = await client.post(f"{PAYMENT_SVC}/payments", json={
                "order_id": order.id,
                "amount": product["price"] * payload.quantity,
            })
            if pay_resp.status_code not in (200, 201):
                order.status = "payment_failed"
                db.commit()
                raise HTTPException(status_code=402, detail="Payment failed")
            payment = pay_resp.json()
            order.payment_id = str(payment["id"])
            order.status = "confirmed" if payment.get("status") == "success" else "payment_failed"
        except httpx.RequestError as e:
            order.status = "failed"
            db.commit()
            raise HTTPException(status_code=502, detail=f"Payment service unavailable: {e}")

    db.commit()
    db.refresh(order)

    # 3. Publish order event to Redis
    try:
        event = {"order_id": order.id, "user_id": order.user_id, "status": order.status}
        redis_client.publish("order-events", json.dumps(event))
        log("INFO", "order event published", **event)
    except Exception as e:
        log("WARN", "redis publish failed", error=str(e))

    return order


@app.get("/orders/{order_id}", response_model=models.OrderResponse)
def get_order(order_id: int, db: Session = Depends(database.get_db)):
    order = db.query(models.OrderORM).filter(models.OrderORM.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
