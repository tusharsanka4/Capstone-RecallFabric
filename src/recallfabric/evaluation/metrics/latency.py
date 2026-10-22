"""Latency percentile metrics (p50 and p95)."""

import math


def calculate_percentiles(latencies_ms: list[float]) -> tuple[float, float]:
    """Compute (p50, p95) latencies in milliseconds."""
    if not latencies_ms:
        return 0.0, 0.0

    sorted_latencies = sorted(latencies_ms)
    n = len(sorted_latencies)

    def percentile(p: float) -> float:
        if n == 1:
            return sorted_latencies[0]
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_latencies[int(k)]
        d0 = sorted_latencies[f] * (c - k)
        d1 = sorted_latencies[c] * (k - f)
        return d0 + d1

    p50 = percentile(0.50)
    p95 = percentile(0.95)
    return round(p50, 2), round(p95, 2)
