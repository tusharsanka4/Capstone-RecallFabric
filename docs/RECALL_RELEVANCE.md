# MCP recall relevance

`RECALLFABRIC_RECALL_MIN_RELEVANCE` defaults to **0.60**, measured against the unchanged
FastEmbed model. It means minimum raw cosine similarity, not composite ranking score.
Higher values are stricter; the valid range is -1 to 1. The effective cutoff is the maximum
of this value and the existing `RECALLFABRIC_RETRIEVAL_MIN_SIMILARITY` candidate floor.

MCP recall retrieves up to `limit * rank_candidate_multiplier` candidates (default 3),
preserves account/status/type/model/dimension filters, applies the existing weighted ranking,
then excludes weak similarities before returning at most `limit` results. Rejected matches
do not enter context or receive access-count updates. There is no fallback fill.
The MCP `search_memory` alias delegates to recall and uses the same filter.

Cosine similarity is `1 - pgvector cosine distance`; higher is better. The existing 0.4
cutoff was active but permissive. Composite ranking also includes importance, confidence,
recency and frequency, so it must not substitute for semantic relevance.

Measured example similarities: Orion matches 0.7287–0.8672; Orion versus notebook 0.4808;
car-query cross-topic matches up to 0.4288; notebook-specific match 0.8239. The 0.60 cutoff
lies within the measured gap. This small sample does not guarantee relevance for every domain.

REST retrieval and its existing explicit min_score behavior remain unchanged. The separate
search_memory_service substring fallback is also unchanged; MCP recall does not use it.

Verification: 35 focused tests passed, 14 database-dependent tests skipped; Ruff passed.
Public SDK tests with two isolated tenants returned one/three Orion matches, excluded the
notebook, returned zero for car ownership, and preserved notebook-specific retrieval and
tenant isolation. Existing user memories were not edited.

Only the backend was reloaded. The existing Cloudflare process, public URL, OAuth metadata,
and all 11 MCP tool definitions remained unchanged. No client reconnection or reauthorization
is required. Actual ChatGPT/Claude UI calls were not repeated; public SDK calls were tested.
No commits or pushes were made.
