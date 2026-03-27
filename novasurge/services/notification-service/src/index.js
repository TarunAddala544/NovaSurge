'use strict';

const express = require('express');
const Redis = require('ioredis');
const client = require('prom-client');

const app = express();
const PORT = process.env.PORT || 3001;
const SERVICE_NAME = 'notification-service';

const REDIS_HOST = process.env.REDIS_HOST || 'redis-service';
const REDIS_PORT = parseInt(process.env.REDIS_PORT || '6379', 10);

// ── Prometheus ───────────────────────────────────────────────────────────────
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
  buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1],
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

const notificationsPerChannel = new client.Gauge({
  name: 'notifications_sent_total',
  help: 'Notifications received per channel',
  labelNames: ['channel'],
  registers: [register],
});

// ── In-memory counters ────────────────────────────────────────────────────────
const channelCounts = {
  'order-events': 0,
  'payment-events': 0,
};

// ── Logger ───────────────────────────────────────────────────────────────────
function log(level, message, extra = {}) {
  console.log(JSON.stringify({
    timestamp: new Date().toISOString(),
    service: SERVICE_NAME,
    level,
    message,
    ...extra,
  }));
}

// ── Redis subscriber ─────────────────────────────────────────────────────────
let activeSubscriber = null;

function connectSubscriber() {
  // Avoid creating a second subscriber if one is already connecting/connected
  if (activeSubscriber) {
    try { activeSubscriber.disconnect(); } catch (_) {}
    activeSubscriber = null;
  }

  const sub = new Redis({ host: REDIS_HOST, port: REDIS_PORT, lazyConnect: true });
  activeSubscriber = sub;

  sub.on('connect', () => log('INFO', 'Redis subscriber connected', { host: REDIS_HOST, port: REDIS_PORT }));
  sub.on('error', (err) => {
    log('ERROR', 'Redis subscriber error', { error: err.message });
  });

  sub.on('message', (channel, message) => {
    try {
      const data = JSON.parse(message);
      channelCounts[channel] = (channelCounts[channel] || 0) + 1;
      notificationsPerChannel.set({ channel }, channelCounts[channel]);
      log('INFO', 'notification received', { channel, data });
    } catch (err) {
      log('ERROR', 'failed to parse message', { channel, message, error: err.message });
    }
  });

  sub.connect()
    .then(() => sub.subscribe('order-events', 'payment-events'))
    .then(() => log('INFO', 'subscribed to channels', { channels: ['order-events', 'payment-events'] }))
    .catch((err) => {
      log('ERROR', 'Redis connect failed, retrying in 5s', { error: err.message });
      activeSubscriber = null;
      setTimeout(connectSubscriber, 5000);
    });

  return sub;
}

connectSubscriber();

// ── Request middleware ───────────────────────────────────────────────────────
app.use((req, res, next) => {
  activeConnections.inc();
  const start = Date.now();
  res.on('finish', () => {
    activeConnections.dec();
    const dur = (Date.now() - start) / 1000;
    const labels = { method: req.method, endpoint: req.path, status_code: String(res.statusCode) };
    httpRequestsTotal.inc(labels);
    httpRequestDuration.observe(labels, dur);
    if (res.statusCode >= 500) serviceErrorsTotal.inc({ method: req.method, endpoint: req.path });
    log(res.statusCode >= 400 ? 'ERROR' : 'INFO', 'request completed', {
      method: req.method, path: req.path, status_code: res.statusCode, duration_ms: Date.now() - start,
    });
  });
  next();
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: SERVICE_NAME, counts: channelCounts, timestamp: new Date().toISOString() });
});

app.get('/metrics', async (req, res) => {
  try {
    res.set('Content-Type', register.contentType);
    res.end(await register.metrics());
  } catch (err) {
    res.status(500).end(err.message);
  }
});

app.listen(PORT, () => log('INFO', `${SERVICE_NAME} listening`, { port: PORT }));
