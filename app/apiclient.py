"""Shared HTTP client for the real data sources (Phase 2).

Every external call goes through ApiClient, which adds:
- authentication: fixed headers or query parameters (API tokens) sent with every request
- rate limiting: a minimum gap between calls to the same provider
- retries: timeouts, 429 and 5xx are retried with exponential backoff; Retry-After is honoured
- caching: successful responses are kept in memory for a per-call TTL; concurrent identical
  requests wait for the first one instead of hitting the provider twice
- circuit breaker: after repeated failures the provider is skipped for a cool-down period,
  so a dead API costs one fast error instead of a timeout on every message
- logging: one line per call with status, latency and cache hits; secrets are never logged

Failures surface as DataSourceError, which the chat turns into a polite message."""
import logging
import threading
import time

import httpx

from .repositories import DataSourceError

log = logging.getLogger("superchat.api")


class ApiClient:
    def __init__(self, name, base_url, *, headers=None, params=None, min_interval=0.25, timeout=8.0,
                 retries=2, backoff=0.5, breaker_threshold=3, breaker_cooldown=60.0, transport=None):
        self.name = name
        self._auth_params = dict(params or {})
        self._client = httpx.Client(base_url=base_url, headers={"User-Agent": "SuperChat/2.0", **(headers or {})},
                                    timeout=timeout, follow_redirects=True, transport=transport)
        self._min_interval = min_interval
        self._retries = retries
        self._backoff = backoff
        self._threshold = breaker_threshold
        self._cooldown = breaker_cooldown
        self._cache = {}
        self._lock = threading.Lock()
        self._key_locks = {}
        self._throttle_lock = threading.Lock()
        self._last_call = 0.0
        self._failures = 0
        self._open_until = 0.0
        self.stats = {"calls": 0, "cache_hits": 0, "errors": 0}

    # ---------- public ----------

    def get_json(self, path, params=None, ttl=300):
        return self._get(path, params, ttl, lambda r: r.json())

    def get_text(self, path, params=None, ttl=300):
        return self._get(path, params, ttl, lambda r: r.text)

    def status(self):
        return {"circuit": "open" if time.monotonic() < self._open_until else "closed", **self.stats}

    # ---------- internals ----------

    def _get(self, path, params, ttl, parse):
        key = (path, tuple(sorted((params or {}).items())))
        with self._lock:
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:
            hit = self._cache.get(key)
            if hit and hit[0] > time.monotonic():
                self.stats["cache_hits"] += 1
                return hit[1]
            if time.monotonic() < self._open_until:
                raise DataSourceError(f"{self.name} is temporarily unavailable")
            value = self._fetch(path, params, parse)
            if ttl:
                self._cache[key] = (time.monotonic() + ttl, value)
            return value

    def _throttle(self):
        with self._throttle_lock:
            wait = self._last_call + self._min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _fetch(self, path, params, parse):
        error = None
        for attempt in range(self._retries + 1):
            self._throttle()
            started = time.monotonic()
            self.stats["calls"] += 1
            try:
                r = self._client.get(path, params={**(params or {}), **self._auth_params})
            except httpx.HTTPError as e:
                error, delay = f"{type(e).__name__}", self._backoff * 2 ** attempt
                log.warning("api=%s GET %s failed: %s (attempt %d)", self.name, path, error, attempt + 1)
            else:
                ms = (time.monotonic() - started) * 1000
                log.info("api=%s GET %s status=%d ms=%.0f", self.name, path, r.status_code, ms)
                if r.status_code < 400:
                    try:
                        value = parse(r)
                    except ValueError:
                        error = "bad response body"
                        break
                    self._failures = 0
                    return value
                error = f"HTTP {r.status_code}"
                if r.status_code != 429 and r.status_code < 500:
                    break  # 4xx other than rate limiting will not get better on retry
                delay = _retry_after(r) or self._backoff * 2 ** attempt
            if attempt < self._retries:
                time.sleep(min(delay, 5.0))
        self.stats["errors"] += 1
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = time.monotonic() + self._cooldown
            log.error("api=%s circuit opened for %.0fs after %d failures", self.name, self._cooldown, self._failures)
        raise DataSourceError(f"{self.name}: {error}")


def _retry_after(response):
    try:
        return float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
