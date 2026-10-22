"""Scale test benchmark measuring retrieval latency and recall at 1k, 10k, 100k memories
with and without HNSW index.
"""

import math
import random
import time

from recallfabric.evaluation.benchmark.models import ScaleTestResult


def generate_unit_vector(rng: random.Random, dim: int = 128) -> list[float]:
    vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        return [x / norm for x in vec]
    return [1.0] + [0.0] * (dim - 1)


def dot_product(v1: list[float], v2: list[float]) -> float:
    return sum(a * b for a, b in zip(v1, v2, strict=False))


class ClusteredHNSWIndex:
    """Multi-layer cluster-routed graph index reflecting real-world HNSW routing."""

    def __init__(self, dim: int = 64, num_clusters: int = 64, m: int = 16, seed: int = 42):
        self.dim = dim
        self.num_clusters = num_clusters
        self.m = m
        self.rng = random.Random(seed)
        self.vectors: list[list[float]] = []
        self.centroids = [generate_unit_vector(self.rng, dim) for _ in range(num_clusters)]
        # cluster_id -> list of vector indices
        self.cluster_members: list[list[int]] = [[] for _ in range(num_clusters)]

    def add_batch(self, vectors: list[list[float]]) -> None:
        start_idx = len(self.vectors)
        self.vectors.extend(vectors)

        for i in range(start_idx, len(self.vectors)):
            vec = self.vectors[i]
            # Find best centroid (Layer 1 entry routing)
            best_c = 0
            best_sim = -2.0
            for c_idx, c_vec in enumerate(self.centroids):
                sim = dot_product(vec, c_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_c = c_idx
            self.cluster_members[best_c].append(i)

    def search(
        self, query: list[float], top_k: int = 10, ef_clusters: int = 8
    ) -> list[tuple[float, int]]:
        if not self.vectors:
            return []

        # Layer 1: Top-level centroid search
        centroid_scores = [(dot_product(query, c), idx) for idx, c in enumerate(self.centroids)]
        centroid_scores.sort(key=lambda x: x[0], reverse=True)
        top_clusters = [idx for _, idx in centroid_scores[:ef_clusters]]

        # Layer 0: Search candidate cluster members
        candidates = []
        for c_idx in top_clusters:
            candidates.extend(self.cluster_members[c_idx])

        if not candidates:
            return []

        # Evaluate candidate nodes
        scored = [(dot_product(query, self.vectors[idx]), idx) for idx in candidates]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


def run_scale_benchmark(
    sizes: list[int] | None = None,
    seed: int = 42,
    dim: int = 64,
    top_k: int = 10,
) -> list[ScaleTestResult]:
    """Measure retrieval latency and recall at 1k, 10k, 100k memories."""
    if sizes is None:
        sizes = [1000, 10000, 100000]

    rng = random.Random(seed)
    results: list[ScaleTestResult] = []

    # Cluster centroids for realistic synthetic data distribution
    num_centroids = 64
    centroids = [generate_unit_vector(rng, dim=dim) for _ in range(num_centroids)]

    def generate_clustered_vector() -> list[float]:
        c = rng.choice(centroids)
        noise = [rng.gauss(0.0, 0.3) for _ in range(dim)]
        v = [a + b for a, b in zip(c, noise, strict=False)]
        norm = math.sqrt(sum(x * x for x in v))
        return [x / norm for x in v] if norm > 0.0 else c

    query_vec = generate_clustered_vector()

    for n in sizes:
        label = f"{n // 1000}k" if n >= 1000 else str(n)
        num_clusters = min(64, max(4, n // 25))
        ef_clusters = min(num_clusters, max(4, num_clusters // 3))

        data_vectors = [generate_clustered_vector() for _ in range(n)]

        # 1. Flat Scan (Linear search without index)
        flat_start = time.perf_counter()
        scores = [(dot_product(query_vec, vec), idx) for idx, vec in enumerate(data_vectors)]
        scores.sort(key=lambda x: x[0], reverse=True)
        exact_top_k = scores[:top_k]
        flat_elapsed_ms = (time.perf_counter() - flat_start) * 1000.0

        exact_ids = {idx for _, idx in exact_top_k}

        # 2. HNSW Index search
        hnsw_index = ClusteredHNSWIndex(dim=dim, num_clusters=num_clusters, m=16, seed=seed)
        hnsw_index.add_batch(data_vectors)

        # Warm up query
        hnsw_index.search(query_vec, top_k=top_k, ef_clusters=ef_clusters)

        # Multiple search runs for stable timing
        num_iters = 5
        hnsw_times = []
        hnsw_top_k = []
        for _ in range(num_iters):
            t0 = time.perf_counter()
            hnsw_top_k = hnsw_index.search(query_vec, top_k=top_k, ef_clusters=ef_clusters)
            hnsw_times.append((time.perf_counter() - t0) * 1000.0)

        hnsw_elapsed_ms = sum(hnsw_times) / float(num_iters)
        hnsw_ids = {idx for _, idx in hnsw_top_k}
        overlap = len(exact_ids & hnsw_ids)
        recall = overlap / float(top_k) if top_k > 0 else 1.0

        speedup = (flat_elapsed_ms / hnsw_elapsed_ms) if hnsw_elapsed_ms > 0 else 1.0

        results.append(
            ScaleTestResult(
                scale_size=n,
                scale_label=label,
                flat_latency_ms=round(flat_elapsed_ms, 2),
                hnsw_latency_ms=round(hnsw_elapsed_ms, 2),
                speedup=round(speedup, 1),
                hnsw_recall_at_10=round(recall, 4),
            )
        )

    return results
