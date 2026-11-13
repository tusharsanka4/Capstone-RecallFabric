"""Generate and validate static OpenAPI and multi-provider tool definitions.

Exports OpenAPI 3.1, OpenAI tools, Anthropic tools, and Gemini function declarations.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from recallfabric.main import create_app
from recallfabric.schemas.v1_tools import (
    ForgetRequest,
    RecallRequest,
    RememberRequest,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
OPENAPI_OUT = ROOT_DIR / "openapi" / "recallfabric.openapi.json"
TOOLS_DIR = ROOT_DIR / "tools"
OPENAI_OUT = TOOLS_DIR / "openai_tools.json"
ANTHROPIC_OUT = TOOLS_DIR / "anthropic_tools.json"
GEMINI_OUT = TOOLS_DIR / "gemini_tools.json"


def inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline Pydantic $defs so schemas are completely self-contained for LLM providers."""
    schema_copy = copy.deepcopy(schema)
    defs = schema_copy.pop("$defs", {})

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if ref.startswith("#/$defs/"):
                    def_name = ref.split("/")[-1]
                    if def_name in defs:
                        resolved = copy.deepcopy(defs[def_name])
                        return _resolve(resolved)
            return {k: _resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return _resolve(schema_copy)


def build_tool_schemas() -> list[dict[str, Any]]:
    """Build canonical list of task-oriented AI tools."""
    remember_params = inline_defs(RememberRequest.model_json_schema())
    remember_params.pop("title", None)

    recall_params = inline_defs(RecallRequest.model_json_schema())
    recall_params.pop("title", None)

    forget_params = inline_defs(ForgetRequest.model_json_schema())
    forget_params.pop("title", None)

    profile_params = {
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": (
                    "Target user identifier (optional; automatically derived from authenticated "
                    "API key when auth is enabled)."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max active memories to include in summary (default: 20).",
                "default": 20,
            },
        },
    }

    capabilities_params = {
        "type": "object",
        "properties": {},
    }

    return [
        {
            "name": "remember",
            "description": (
                "Store an explicit memory statement or extract atomic facts from conversation "
                "text. Use `content` for direct storage (preferences, facts, goals, etc.) "
                "with automatic deduplication and conflict superseding. Set `extract=true` "
                "to automatically analyze conversation turns and extract isolated facts."
            ),
            "parameters": remember_params,
        },
        {
            "name": "recall",
            "description": (
                "Retrieve relevant user memories for a query, ranked by multi-factor relevance "
                "(semantic similarity, importance, recency, and access frequency). Returns a "
                "structured list of memories and a pre-formatted, character-budgeted `context` "
                "markdown string ready for system prompt injection."
            ),
            "parameters": recall_params,
        },
        {
            "name": "forget",
            "description": (
                "Delete a user memory either by its exact UUID (`memory_id`), or by semantically "
                "finding the best match for a `query`. When searching by query without "
                "`confirm=true`, the endpoint returns the candidate memory awaiting confirmation. "
                "Pass `confirm=true` to confirm permanent deletion."
            ),
            "parameters": forget_params,
        },
        {
            "name": "profile",
            "description": (
                "Retrieve a compact summary of the user's active memories organized by category "
                "(preferences, profile, goals, skills, facts). Returns a pre-assembled markdown "
                "profile ready for context injection."
            ),
            "parameters": profile_params,
        },
        {
            "name": "capabilities",
            "description": (
                "Inspect service version, active embedding model details, supported memory "
                "categories, enabled security features, and operational limits."
            ),
            "parameters": capabilities_params,
        },
    ]


def generate_all() -> dict[Path, str]:
    """Generate serialized contents for all 4 schema artifacts."""
    app = create_app()
    openapi_spec = app.openapi()
    openapi_json = json.dumps(openapi_spec, indent=2, sort_keys=False) + "\n"

    tools = build_tool_schemas()

    # 1. OpenAI function calling format
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in tools
    ]
    openai_json = json.dumps(openai_tools, indent=2) + "\n"

    # 2. Anthropic tool use format
    anthropic_tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in tools
    ]
    anthropic_json = json.dumps(anthropic_tools, indent=2) + "\n"

    # 3. Gemini function declarations format
    gemini_tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        }
        for t in tools
    ]
    gemini_json = json.dumps(gemini_tools, indent=2) + "\n"

    return {
        OPENAPI_OUT: openapi_json,
        OPENAI_OUT: openai_json,
        ANTHROPIC_OUT: anthropic_json,
        GEMINI_OUT: gemini_json,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and check OpenAPI and AI tool schemas.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether generated files on disk are up to date without writing.",
    )
    args = parser.parse_args()

    generated = generate_all()

    if args.check:
        drift_detected = False
        for path, expected_content in generated.items():
            if not path.is_file():
                print(f"ERROR: Missing schema file: {path.relative_to(ROOT_DIR)}", file=sys.stderr)
                drift_detected = True
                continue
            actual_content = path.read_text(encoding="utf-8")
            if actual_content != expected_content:
                rel = path.relative_to(ROOT_DIR)
                print(
                    f"ERROR: Schema drift detected in {rel}! "
                    f"Run 'python scripts/generate_tool_schemas.py' to update.",
                    file=sys.stderr,
                )
                drift_detected = True
        if drift_detected:
            sys.exit(1)
        print("OK: All OpenAPI and tool schemas are up to date.")
        sys.exit(0)

    # Write files
    for path, content in generated.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"Generated {path.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
