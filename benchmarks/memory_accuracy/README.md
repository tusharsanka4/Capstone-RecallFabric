# RecallFabric memory accuracy benchmark

This benchmark evaluates production extraction, confirmed recommendation handling,
reconciliation, provenance, and retrieval against 200 reviewed synthetic conversations.
`development.jsonl` contains 40 cases. The frozen `evaluation.jsonl` contains 160 cases and
must not be used to tune production behavior after inspecting failures.

## Safety model

Every scenario uses a fresh `rfbench_*` PostgreSQL schema. The runner accepts only a local,
non-production database, migrates that schema, verifies the `public.memories` row count before
and after, and drops only the schema it created. It never resets the database or Docker volume.
The acknowledgement flag is required because schema creation and owned-schema cleanup are writes.

## PowerShell commands

```powershell
# No database access
.\.venv\Scripts\python.exe -m benchmarks.memory_accuracy validate

# One fixed-conversation smoke scenario using real Ollama and production extraction
.\.venv\Scripts\python.exe -m benchmarks.memory_accuracy run `
  --split development --mode replay --limit 1 `
  --env-file .env.local --confirm-disposable-local-db

# Select by stable ID or category
.\.venv\Scripts\python.exe -m benchmarks.memory_accuracy run `
  --split development --mode replay `
  --scenario ma-accepted-assistant-recommendations-001 `
  --env-file .env.local --confirm-disposable-local-db

# Live assistant generation plus extraction
.\.venv\Scripts\python.exe -m benchmarks.memory_accuracy run `
  --split development --mode end-to-end --limit 1 `
  --env-file .env.local --confirm-disposable-local-db

# Retrieval-only run with gold memories plus 12 labeled distractors
.\.venv\Scripts\python.exe -m benchmarks.memory_accuracy run `
  --split development --mode retrieval-only --limit 1 `
  --env-file .env.local --confirm-disposable-local-db

# Resume the deterministic run ID after interruption
.\.venv\Scripts\python.exe -m benchmarks.memory_accuracy run `
  --split development --mode replay --resume `
  --env-file .env.local --confirm-disposable-local-db

# Regenerate reports from an existing run
.\.venv\Scripts\python.exe -m benchmarks.memory_accuracy report <run-id>
```

Replay mode uses the fixed assistant turns in the dataset and isolates extraction and memory
behavior. End-to-end mode uses the real chat provider and records its generated conversation.
Retrieval-only mode is labeled separately and does not claim extraction accuracy.

Artifacts are written under `results/<run-id>/`: `manifest.json`, `results.jsonl`,
`aggregate_metrics.json`, category and failure CSV/JSONL files, and `REPORT.md`. Results include
raw predictions, gold labels, provenance events, retrieval rankings, latencies, errors, and metric
numerators. Secret values are excluded.

