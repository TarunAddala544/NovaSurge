import os
import json
import time
import random
import logging
from typing import List

import redis as redis_lib
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session
from prometheus_client import (
    Counter, Histogram, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
)

import database
import models

# ── Logging ──────────────────────────────────────────────────────────────────
SERVICE_NAME = "product-service"

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


# ── Prometheus ───────────────────────────────────────────────────────────────
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

# ── Redis ────────────────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "redis-service")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="product-service")

database.Base.metadata.create_all(bind=database.engine)


@app.on_event("startup")
def seed_products():
    db = database.SessionLocal()
    try:
        count = db.query(models.ProductORM).count()
        if count == 0:
            seed_data = [
                ("Laptop Pro 15", 1299.99, 50, "Electronics"),
                ("Wireless Mouse", 29.99, 200, "Electronics"),
                ("USB-C Hub", 49.99, 150, "Electronics"),
                ("Mechanical Keyboard", 89.99, 100, "Electronics"),
                ("4K Monitor", 399.99, 40, "Electronics"),
                ("Standing Desk", 499.99, 30, "Furniture"),
                ("Ergonomic Chair", 349.99, 25, "Furniture"),
                ("Desk Lamp", 39.99, 120, "Furniture"),
                ("Notebook Set", 14.99, 300, "Stationery"),
                ("Ballpoint Pens 10pk", 7.99, 500, "Stationery"),
                ("Sticky Notes", 5.99, 400, "Stationery"),
                ("Whiteboard", 79.99, 60, "Office"),
                ("Dry Erase Markers", 9.99, 250, "Office"),
                ("File Organizer", 24.99, 80, "Office"),
                ("Webcam HD", 69.99, 90, "Electronics"),
                ("Headphones Pro", 149.99, 70, "Electronics"),
                ("Microphone USB", 99.99, 55, "Electronics"),
                ("Phone Stand", 19.99, 180, "Accessories"),
                ("Cable Management Kit", 15.99, 200, "Accessories"),
                ("Laptop Sleeve", 34.99, 110, "Accessories"),
            ]
            for name, price, stock, category in seed_data:
                db.add(models.ProductORM(name=name, price=price, stock=stock, category=category))
            db.commit()
            log("INFO", "seeded 20 products")
    finally:
        db.close()


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
    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/products", response_model=List[models.ProductResponse])
def list_products(db: Session = Depends(database.get_db)):
    return db.query(models.ProductORM).all()


@app.get("/products/{product_id}", response_model=models.ProductResponse)
def get_product(product_id: int, db: Session = Depends(database.get_db)):
    cache_key = f"products:{product_id}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            log("INFO", "cache hit", product_id=product_id)
            return json.loads(cached)
    except Exception as e:
        log("WARN", "redis error", error=str(e))

    product = db.query(models.ProductORM).filter(models.ProductORM.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    data = models.ProductResponse.from_orm(product).dict()
    try:
        redis_client.setex(cache_key, 60, json.dumps(data))
    except Exception as e:
        log("WARN", "redis write error", error=str(e))

    return data


@app.post("/products", response_model=models.ProductResponse, status_code=201)
def create_product(payload: models.ProductCreate, db: Session = Depends(database.get_db)):
    product = models.ProductORM(**payload.dict())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product
