const BASE = import.meta.env.VITE_API_BASE || '/api';
const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };
const MAX_BUFFER = 200;
const FLUSH_INTERVAL = 8000;
const REMOTE_ENABLED = import.meta.env.VITE_LOG_REMOTE === 'true';

const buffer = [];
const timestamps = {};
let flushing = false;

function stamp() {
  return new Date().toISOString();
}

function fmt(level, source, message) {
  return `[${stamp()}] [${level.toUpperCase()}] [${source}] ${message}`;
}

function out(level, message) {
  const fn = console[level] || console.log;
  fn(message);
}

async function flush() {
  if (!REMOTE_ENABLED || flushing || buffer.length === 0) return;
  flushing = true;
  const batch = buffer.splice(0, buffer.length);
  try {
    await fetch(`${BASE}/logs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ logs: batch }),
    });
  } catch (e) {
    out('warn', `[logger] remote flush failed: ${e.message}`);
  } finally {
    flushing = false;
  }
}

setInterval(flush, FLUSH_INTERVAL);
window.addEventListener('beforeunload', () => {
  if (buffer.length) {
    navigator.sendBeacon(`${BASE}/logs`, JSON.stringify({ logs: buffer.splice(0, buffer.length) }));
  }
});

function push(level, source, message, meta) {
  const entry = {
    level,
    source,
    message,
    timestamp: stamp(),
    url: typeof window !== 'undefined' ? window.location.pathname : '',
  };
  if (meta !== undefined) entry.meta = meta;
  buffer.push(entry);
  if (buffer.length > MAX_BUFFER) buffer.splice(0, buffer.length - MAX_BUFFER);
}

function throttle(key, level, source, message, minGapMs = 2000) {
  const now = Date.now();
  if (timestamps[key] && now - timestamps[key] < minGapMs) return;
  timestamps[key] = now;
  log(level, source, message);
}

function log(level, source, message, meta) {
  const lvl = LEVELS[level] ?? LEVELS.info;
  if (lvl >= LEVELS.warn) {
    out(level === 'warn' ? 'warn' : 'error', fmt(level, source, message), meta);
  } else {
    out('log', fmt(level, source, message), meta);
  }
  push(level, source, message, meta);
  if (lvl >= LEVELS.warn && REMOTE_ENABLED) flush();
}

const logger = {
  debug: (source, message, meta) => log('debug', source, message, meta),
  info: (source, message, meta) => log('info', source, message, meta),
  warn: (source, message, meta) => log('warn', source, message, meta),
  error: (source, message, meta) => log('error', source, message, meta),
  throttle,
  flush,
};

export default logger;
