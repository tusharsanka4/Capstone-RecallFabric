# Project-aware memory

## Design

Existing `Memory.attributes` maps to PostgreSQL JSONB metadata. No migration, backfill,
new service, model, threshold, tool argument or authentication change is required.

New explicit project facts carry derived metadata such as:

```json
{"project_entities": [{"type": "project", "key": "nova", "name": "Project Nova"}]}
```

An explicit `Project <name>` establishes a project. Keys use Unicode NFKC normalization
and case folding; display names retain their spelling. Matching uses exact token boundaries,
not fuzzy similarity. Nova and Novaa stay separate. Bare Nova resolves only when this
tenant's stored active memories establish it as a project. General preferences are unlabelled.
No project is guessed from an assistant suggestion, an omitted conversation subject, or an
unknown bare word. Existing accepted-decision slots and quotes are preserved unchanged.

The shared helper labels new memory/revision writes across MCP, REST, extraction, dedupe,
conflict storage and shared services. Explicit ID-bound corrections can inherit their prior
revision's project when the replacement text omits the name. Explicit renames replace the label.
Bare-name legacy memories are resolved in context at read time; they need no database rewrite.

## Retrieval and state

Each semantic lookup builds a tenant-local project catalogue from rows with the requested
status (active for MCP). It reads/decrypts existing text and metadata without backfilling.
When the query resolves named projects, their memory IDs constrain the SQL query before
vector ordering/LIMIT. Other project IDs and ungrouped facts cannot crowd out candidates.
Comparison/multiple-name queries permit all requested projects. Queries with no resolved
name retain existing semantic behavior, including broad project and general preference queries.

Existing model/dimension/type/status/tenant predicates, weighted ranking, and relevance
thresholds remain intact. Matching a project does not bypass relevance: results still mean
up to K relevant matches. `recall`/`search_memory`, REST semantic retrieval and the shared
search path use the same project scope. The shared substring fallback is scoped too.
MCP recall items gain an `entities` array; existing scores and fields remain unchanged.
All 11 tool definitions, including input/output schemas and annotations, remain identical.

Duplicate/conflict/accepted-slot candidate queries use the same scope for named projects,
so similar technology vocabulary does not consolidate or supersede a different project.
Within a project, existing acceptance and conflict classification rules are unchanged.
Active-only recall excludes superseded Mercury/MongoDB revisions; history remains available.

## Live verification

An isolated tenant was seeded with Nova and Atlas facts, including untagged legacy bare-name
facts, notebook and backend-language preferences. Through the existing public HTTPS MCP:

- Nova: four Nova memories, no Atlas contamination.
- Continue Nova: the same four memories.
- Atlas stack: four Atlas memories only.
- Compare Atlas and Nova: eight memories from both projects.
- Broad projects: six relevant memories from both projects; no forced top-K fill.
- Notebook and backend-language preference queries continued to work.
- Public remember/update persisted Mercury metadata. PostgreSQL became the active revision;
  MongoDB remained superseded. A different-project Vega/React write preserved all seed rows.

Only synthetic test data was created/updated. No existing user memories were backfilled.
The same Cloudflare process and URL were retained. Backend-only reload was followed by
/ready, protected /mcp/, OAuth discovery, full MCP discovery and authenticated calls.
No client reconnection or reauthorization is required. ChatGPT/Claude UI scenarios were not
repeated by the agent; the existing endpoint was exercised using the official MCP SDK.

## Limits

- Initial deterministic extraction supports single-token/hyphenated project names. Ambiguous
  multiword names are left unclassified rather than truncated into another project's identity.
- Unknown bare aliases and project-less accepted decisions remain unscoped. Explicit project
  names are needed to establish context; this does not infer an unstated conversation subject.
- Homonyms can remain ambiguous; there is no semantic disambiguator or entity graph.
- The catalogue scans a tenant's memories per lookup. It suits the demo scale; a persisted,
  indexed registry could be considered later if account size makes the scan expensive.
- A relevant project fact below the unchanged similarity cutoff is still omitted. Broad
  queries return relevant projects up to the requested limit, not a guaranteed full inventory.
