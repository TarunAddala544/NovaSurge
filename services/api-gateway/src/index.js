'use strict';

const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const client = require('prom-client');

const app = express();
const PORT = process.env.PORT || 3000;
const SERVICE_NAME = 'api-gateway';

// ── Prometheus metrics ───────────────────────────────────────────────────────
const register = new client.Registry();
client.collectDefaultMetrics({ register });

const httpRequestsTotal = new client.Counter({
  name: 'http_requests_total',
  help: 'Total HTTP requests',
  labelNames: ['method', 'endpoint', 'status_code'],
  registers: [register],
});

const httpRequestDuration = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'HTTP request duration in seconds',
  labelNames: ['method', 'endpoint', 'status_code'],
  buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
  registers: [register],
});

const serviceErrorsTotal = new client.Counter({
  name: 'service_errors_total',
  help: 'Total service errors',
  labelNames: ['method', 'endpoint'],
  registers: [register],
});

const activeConnections = new client.Gauge({
  name: 'active_connections',
  help: 'Active connections',
  registers: [register],
});

// ── Structured JSON logger ───────────────────────────────────────────────────
function log(level, message, extra = {}) {
  const entry = {
    timestamp: new Date().toISOString(),
    service: SERVICE_NAME,
    level,
    message,
    ...extra,
  };
  console.log(JSON.stringify(entry));
}

// ── Request instrumentation middleware ──────────────────────────────────────
app.use((req, res, next) => {
  activeConnections.inc();
  const start = Date.now();

  res.on('finish', () => {
    activeConnections.dec();
    const durationMs = Date.now() - start;
    const durationSec = durationMs / 1000;
    const endpoint = req.route ? req.route.path : req.path;
    const labels = {
      method: req.method,
      endpoint,
      status_code: String(res.statusCode),
    };

    httpRequestsTotal.inc(labels);
    httpRequestDuration.observe(labels, durationSec);

    if (res.statusCode >= 500) {
      serviceErrorsTotal.inc({ method: req.method, endpoint });
    }

    log(res.statusCode >= 400 ? 'ERROR' : 'INFO', 'request completed', {
      method: req.method,
      path: req.path,
      status_code: res.statusCode,
      duration_ms: durationMs,
    });
  });

  next();
});

// ── Health & metrics ─────────────────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: SERVICE_NAME, timestamp: new Date().toISOString() });
});

app.get('/metrics', async (req, res) => {
  try {
    res.set('Content-Type', register.contentType);
    res.end(await register.metrics());
  } catch (err) {
    res.status(500).end(err.message);
  }
});

// ── Proxy helpers ────────────────────────────────────────────────────────────
const PRODUCT_SVC = process.env.PRODUCT_SERVICE_URL || 'http://product-service:8001';
const ORDER_SVC   = process.env.ORDER_SERVICE_URL   || 'http://order-service:8002';
const PAYMENT_SVC = process.env.PAYMENT_SERVICE_URL || 'http://payment-service:8003';

function makeProxy(target, pathRewrite) {
  return createProxyMiddleware({
    target,
    changeOrigin: true,
    pathRewrite,
    on: {
      error: (err, req, res) => {
        log('ERROR', 'proxy error', { target, error: err.message });
        serviceErrorsTotal.inc({ method: req.method, endpoint: req.path });
        res.status(502).json({ error: 'Bad Gateway', detail: err.message });
      },
    },
  });
}

// ── Routes ───────────────────────────────────────────────────────────────────
app.use('/products', makeProxy(PRODUCT_SVC));
app.use('/orders',   makeProxy(ORDER_SVC));
app.use('/payments', makeProxy(PAYMENT_SVC));

// ── Start ─────────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  log('INFO', `${SERVICE_NAME} listening`, { port: PORT });
});
