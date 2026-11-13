# LLM Provider Setup

RecallFabric selects chat and extraction providers independently through
environment variables. Provider credentials are read only by the API process;
they are not returned by `/providers`, written to application logs, or sent to
the dashboard.

## OpenAI

Set these variables in a server-side `.env` file or deployment secret store:

```powershell
$env:RECALLFABRIC_LLM_PROVIDER = "openai"
$env:RECALLFABRIC_CHAT_PROVIDER = "openai"
$env:RECALLFABRIC_EXTRACTION_PROVIDER = "openai"
$env:RECALLFABRIC_OPENAI_API_KEY = "<your-openai-api-key>"
$env:RECALLFABRIC_OPENAI_BASE_URL = "https://api.openai.com/v1"
$env:RECALLFABRIC_OPENAI_MODEL = "gpt-4o-mini"
$env:RECALLFABRIC_OPENAI_CHAT_MODEL = "gpt-4o-mini"
$env:RECALLFABRIC_OPENAI_EXTRACTION_MODEL = "gpt-4o-mini"
$env:RECALLFABRIC_LLM_TIMEOUT = "60.0"
```

`RECALLFABRIC_OPENAI_CHAT_MODEL` and
`RECALLFABRIC_OPENAI_EXTRACTION_MODEL` are optional. If either is empty,
`RECALLFABRIC_OPENAI_MODEL` is used.

## Other supported providers

Anthropic and Gemini use the same provider-selection variables with their own
credentials, URLs, and model names:

```text
RECALLFABRIC_ANTHROPIC_API_KEY=<server-side-secret>
RECALLFABRIC_ANTHROPIC_BASE_URL=https://api.anthropic.com
RECALLFABRIC_ANTHROPIC_MODEL=claude-3-haiku-20240307
RECALLFABRIC_ANTHROPIC_CHAT_MODEL=
RECALLFABRIC_ANTHROPIC_EXTRACTION_MODEL=

RECALLFABRIC_GEMINI_API_KEY=<server-side-secret>
RECALLFABRIC_GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
RECALLFABRIC_GEMINI_MODEL=gemini-1.5-flash
RECALLFABRIC_GEMINI_CHAT_MODEL=
RECALLFABRIC_GEMINI_EXTRACTION_MODEL=
```

Set `RECALLFABRIC_CHAT_PROVIDER` and/or
`RECALLFABRIC_EXTRACTION_PROVIDER` to `anthropic` or `gemini` as needed.
`RECALLFABRIC_LLM_PROVIDER` remains the fallback when a task-specific provider
is not set.

## Ollama

The existing local setup remains supported:

```powershell
$env:RECALLFABRIC_LLM_PROVIDER = "ollama"
$env:RECALLFABRIC_CHAT_PROVIDER = "ollama"
$env:RECALLFABRIC_EXTRACTION_PROVIDER = "ollama"
$env:RECALLFABRIC_LLM_BASE_URL = "http://host.docker.internal:11434/v1"
$env:RECALLFABRIC_LLM_API_KEY = "ollama"
$env:RECALLFABRIC_CHAT_MODEL = "qwen2.5:3b-instruct"
$env:RECALLFABRIC_EXTRACTION_MODEL = "qwen2.5:3b-instruct"
$env:RECALLFABRIC_LLM_TIMEOUT = "60.0"
```

For a host process, use `http://127.0.0.1:11434/v1` instead.

## Container restart

From the project directory, set the database password required by the existing
isolated Compose project, then recreate only the API:

```powershell
$env:RECALLFABRIC_DB_PASSWORD = "<existing-isolated-db-password>"
docker compose -p recallfabric-complete -f compose.yaml -f compose.complete.yaml `
  up -d --no-deps --build --force-recreate api
Invoke-WebRequest http://127.0.0.1:8001/health
Invoke-WebRequest http://127.0.0.1:8001/ready
Invoke-WebRequest http://127.0.0.1:8001/providers
```

Do not run `docker compose down -v`; it deletes database volumes.

## Smoke testing after configuration

After supplying a valid provider key, test without printing the key:

```powershell
$body = @{
  user_id = "provider-smoke-test"
  message = "Reply with a short greeting."
  extract = $false
} | ConvertTo-Json
Invoke-WebRequest -Method Post -Uri http://127.0.0.1:8001/chat `
  -ContentType "application/json" -Body $body

$extraction = @{
  user_id = "provider-extraction-smoke"
  source = "provider-extraction-smoke"
  text = "I prefer concise technical explanations."
  dry_run = $true
  deduplicate = $true
} | ConvertTo-Json
Invoke-WebRequest -Method Post -Uri http://127.0.0.1:8001/extraction `
  -ContentType "application/json" -Body $extraction
```

For the complete mocked local memory pipeline (extraction, validation,
embedding, PostgreSQL persistence, semantic recall, context-aware chat,
versioning, provenance, deletion, and user isolation), run:

```powershell
$env:RECALLFABRIC_RUN_DB_TESTS = "1"
uv run pytest -q tests/test_memories_api.py::test_end_to_end_extraction_retrieval_chat_lifecycle
```

This test does not call a hosted provider.

## Errors and troubleshooting

- `503`: the provider service is unreachable, or a required API key is absent.
- `504`: the provider exceeded `RECALLFABRIC_LLM_TIMEOUT`.
- `502`: the provider returned an unsupported or malformed response.
- `/providers` reports only boolean `configured`/`available` fields; it never
  returns credentials.
- A missing hosted-provider key is intentionally reported as unavailable.
  Add the key to the server environment and recreate the API container.
- Hosted-provider live connections were not run as part of local acceptance;
  they require the operator's own credentials and may incur provider charges.

Store `.env` outside source control. The repository ignores `.env` and
`.env.*`, while `.env.example` contains placeholders only.
