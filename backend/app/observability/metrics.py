"""In-process request metrics and their Prometheus text exposition.

Each API process keeps its own counters (requests by route, method and status class, and
a latency histogram per route). Queue, worker and storage figures come from the database
when they are read, so they cover every process, workers included.
"""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field

# Latency buckets in seconds (the Prometheus histogram's upper bounds).
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
# Recent durations kept per route for the percentiles shown in the UI.
RECENT = 1000


@dataclass
class RouteStats:
    count: int = 0
    errors: int = 0  # 5xx responses
    total_seconds: float = 0.0
    max_seconds: float = 0.0
    buckets: list[int] = field(default_factory=lambda: [0] * len(BUCKETS))
    by_status: dict[str, int] = field(default_factory=dict)  # "2xx", "4xx", ...
    recent: deque = field(default_factory=lambda: deque(maxlen=RECENT))


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.routes: dict[tuple[str, str], RouteStats] = {}
        self.started = time.time()

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        status_class = f"{status // 100}xx"
        with self._lock:
            stats = self.routes.setdefault((method, route), RouteStats())
            stats.count += 1
            stats.errors += status >= 500
            stats.total_seconds += seconds
            stats.max_seconds = max(stats.max_seconds, seconds)
            stats.by_status[status_class] = stats.by_status.get(status_class, 0) + 1
            stats.recent.append(seconds)
            for i, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    stats.buckets[i] += 1
                    break

    def snapshot(self) -> list[dict]:
        """Per route: counts, error rate and latency percentiles (milliseconds)."""
        with self._lock:
            items = [(key, stats, list(stats.recent)) for key, stats in self.routes.items()]
        rows = []
        for (method, route), stats, recent in items:
            p50, p95 = percentile(recent, 0.5), percentile(recent, 0.95)
            rows.append(
                {
                    "method": method,
                    "route": route,
                    "count": stats.count,
                    "errors": stats.errors,
                    "by_status": dict(stats.by_status),
                    "avg_ms": round(1000 * stats.total_seconds / stats.count, 2),
                    "p50_ms": round(1000 * p50, 2) if p50 is not None else None,
                    "p95_ms": round(1000 * p95, 2) if p95 is not None else None,
                    "max_ms": round(1000 * stats.max_seconds, 2),
                }
            )
        return sorted(rows, key=lambda r: -r["count"])

    def reset(self) -> None:
        with self._lock:
            self.routes.clear()

    def prometheus(self) -> list[str]:
        lines = [
            "# HELP atlas_http_requests_total HTTP requests handled by this API process.",
            "# TYPE atlas_http_requests_total counter",
        ]
        with self._lock:
            snapshot = [
                (key, dict(s.by_status), list(s.buckets), s.count, s.total_seconds)
                for key, s in self.routes.items()
            ]
        for (method, route), by_status, _, _, _ in snapshot:
            for status_class, n in sorted(by_status.items()):
                labels = _labels(method=method, route=route, status=status_class)
                lines.append(f"atlas_http_requests_total{{{labels}}} {n}")
        lines += [
            "# HELP atlas_http_request_duration_seconds Request latency by route.",
            "# TYPE atlas_http_request_duration_seconds histogram",
        ]
        for (method, route), _, buckets, count, total in snapshot:
            cumulative = 0
            for bound, n in zip(BUCKETS, buckets, strict=True):
                cumulative += n
                labels = _labels(method=method, route=route, le=_number(bound))
                lines.append(f"atlas_http_request_duration_seconds_bucket{{{labels}}} {cumulative}")
            labels = _labels(method=method, route=route)
            lines.append(
                f'atlas_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}'
            )
            lines.append(f"atlas_http_request_duration_seconds_sum{{{labels}}} {total:.6f}")
            lines.append(f"atlas_http_request_duration_seconds_count{{{labels}}} {count}")
        return lines


def _number(value: float) -> str:
    return repr(float(value))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**labels: str) -> str:
    return ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())


def gauge(name: str, help_text: str, values: list[tuple[dict[str, str], float]]) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for labels, value in values:
        rendered = f"{{{_labels(**labels)}}}" if labels else ""
        lines.append(f"{name}{rendered} {_number(value)}")
    return lines


REQUESTS = RequestMetrics()
