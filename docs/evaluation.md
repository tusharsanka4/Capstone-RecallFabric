# Evaluation & Benchmark Results

RecallFabric undergoes rigorous automated benchmarking across synthetic and multi-session conversational evaluation datasets.

For the complete, unedited experimental data and generated charts, see the [Full M18 Benchmark Report](file:///c:/Users/PC01/Desktop/Aarush/COLLEGE/Projects/capstone/evaluation/results/REPORT.md).

---

## 1. Executive Summary

Three distinct memory architectures were benchmarked across multi-session evaluation suites:
1. **Baseline LLM (No Memory)**: Standard zero-shot LLM without cross-session memory.
2. **Basic Vector Memory**: Naive vector database storing every message with raw top-k cosine similarity retrieval.
3. **RecallFabric**: Full production pipeline with atomic fact extraction, distractor filtering, lock-backed deduplication, LLM-based conflict resolution, and multi-factor hybrid ranking.

---

## 2. Head-to-Head Performance

| Metric | Baseline (No Memory) | Basic Vector | RecallFabric | Improvement |
|---|:---:|:---:|:---:|:---:|
| **Precision @ 1** | 0.27 | 0.50 | **0.64** | **+28%** over Basic Vector |
| **Recall @ 1** | 0.27 | 0.77 | **0.92** | **+19%** over Basic Vector |
| **Exact Match** | 0.00 | 0.44 | **0.64** | **+45%** over Basic Vector |
| **Conflict Resolution** | 0.00 | 0.42 | **0.84** | **2.0x** over Basic Vector |
| **Distractor Rejection** | 1.00 (blind) | 0.00 (stores all) | **1.00** | Filters 100% of conversational noise |
| **Memories per Conversation** | 0.0 | 8.0 (bloated) | **2.7** (distilled) | **66% context reduction** |
| **Retrieval Latency (p50)** | 0.0 ms | 0.3 ms | **0.3 ms** | Sub-millisecond vector retrieval |

---

## 3. Subsystem Contributions (Ablation Analysis)

By isolating components, the impact of each subsystem on final retrieval accuracy was measured:

- **Conflict Resolution Engine**: When disabled, conflict resolution accuracy drops from **84% down to 30%**, because obsolete user facts (e.g. "I drink milk" vs "I am now vegan") compete directly with current facts.
- **Extraction & Distractor Filtering**: Disabling extraction filtering causes distractor rejection to collapse from **100% to 3%**, flooding the vector database with chit-chat and filler text.
- **Deduplication Locking**: Deduplication eliminates redundant vector storage, reducing character consumption by up to **66%**.
- **Multi-Factor Ranking**: Accounting for recency decay, frequency, and importance improves precision by **+11%** over raw cosine similarity.

---

## 4. Vector Scaling & HNSW Indexing

Benchmarking flat sequential scan vs. PostgreSQL HNSW vector indexing across corpus scales:

- **1k vectors**: HNSW delivers **4.0x speedup** (1.65 ms vs 6.59 ms).
- **10k vectors**: HNSW delivers **2.7x speedup** (22.1 ms vs 60.3 ms).
- **100k vectors**: HNSW delivers **4.3x speedup** (223.7 ms vs 955.9 ms) with **100% Recall@10**.

---

## Running Benchmarks Locally

To reproduce the benchmark suite:

```bash
# Run full evaluation pipeline
python evaluation/run_benchmarks.py --runs 3 --output-dir evaluation/results
```
