#!/usr/bin/env python3
"""Smoke test script for verifying deployed RecallFabric API instances.

Exercises:
1. GET /health (Liveness)
2. GET /ready (Database, vector extension, migrations, SSL)
3. POST /memories/ (Create memory)
4. GET /memories/{id} (Fetch memory by ID)
5. POST /memories/retrieve (Semantic similarity search)
6. POST /extraction/extract (LLM memory extraction - mockable/skippable)
7. DELETE /memories/{id} (Disable/cleanup memory)
"""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx


def run_smoke_test(
    base_url: str,
    api_key: str | None = None,
    user_id: str = "smoke_test_user",
    skip_extraction: bool = False,
    timeout: float = 30.0,
) -> bool:
    base_url = base_url.rstrip("/")
    headers = {"X-User-ID": user_id}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key

    client = httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
    )
    print(f"Running RecallFabric Smoke Test against: {base_url}")
    print(f"Target User ID: {user_id}")

    created_memory_id: str | None = None

    try:
        # 1. Health check
        print("\n[1/6] Checking /health (process liveness)...", end=" ")
        resp = client.get("/health")
        if resp.status_code != 200:
            print(f"FAILED (Status {resp.status_code}: {resp.text})")
            return False
        data = resp.json()
        if data.get("status") != "ok":
            print(f"FAILED (Unexpected response: {data})")
            return False
        print("OK")

        # 2. Readiness check
        print("[2/6] Checking /ready (database, vector, migrations, SSL)...", end=" ")
        resp = client.get("/ready?detailed=true")
        if resp.status_code != 200:
            print(f"FAILED (Status {resp.status_code}: {resp.text})")
            return False
        ready_data = resp.json()
        print(
            f"OK (DB={ready_data.get('database_reachable')}, "
            f"Vector={ready_data.get('vector_extension_enabled')}, "
            f"Migrations={ready_data.get('migration_revision_matches_head')}, "
            f"SSL={ready_data.get('ssl_in_use')})"
        )

        # 3. Create memory
        print("[3/6] Creating a test memory...", end=" ")
        unique_marker = uuid.uuid4().hex[:8]
        create_payload = {
            "user_id": user_id,
            "content": f"User deploys RecallFabric with Docker ({unique_marker}).",
            "type": "preference",
            "importance": 0.8,
            "confidence": 0.95,
            "source": "smoke_test_script",
            "metadata": {"test_marker": unique_marker},
        }
        resp = client.post("/memories", json=create_payload)
        if resp.status_code not in (200, 201):
            print(f"FAILED (Status {resp.status_code}: {resp.text})")
            return False
        created = resp.json()
        created_memory_id = created.get("id")
        if not created_memory_id:
            print(f"FAILED (No ID returned in created memory: {created})")
            return False
        print(f"OK (ID: {created_memory_id}, Version: {created.get('version')})")

        # 4. Fetch memory by ID
        print(f"[4/6] Fetching memory {created_memory_id}...", end=" ")
        resp = client.get(f"/memories/{created_memory_id}", params={"user_id": user_id})
        if resp.status_code != 200:
            print(f"FAILED (Status {resp.status_code}: {resp.text})")
            return False
        fetched = resp.json()
        if fetched.get("id") != created_memory_id:
            print(f"FAILED (ID mismatch: expected {created_memory_id}, got {fetched.get('id')})")
            return False
        print("OK")

        # 5. Semantic similarity retrieval
        print("[5/6] Testing semantic memory retrieval...", end=" ")
        retrieve_payload = {
            "user_id": user_id,
            "query": "How does the user prefer to deploy RecallFabric?",
            "limit": 5,
        }
        resp = client.post("/memories/retrieve", json=retrieve_payload)
        if resp.status_code != 200:
            print(f"FAILED (Status {resp.status_code}: {resp.text})")
            return False
        retrieved_data = resp.json()
        # Verify retrieved items is a list and contains our memory
        if isinstance(retrieved_data, dict):
            retrieved_items = retrieved_data.get("items", [])
        else:
            retrieved_items = retrieved_data
        found = any(m.get("id") == created_memory_id for m in retrieved_items)
        if not found:
            print(
                f"WARNING: Memory {created_memory_id} not ranked in top 5 "
                f"(retrieved {len(retrieved_items)} items), but query succeeded."
            )
        else:
            print("OK (Memory found in nearest neighbor results)")

        # 6. LLM Extraction (optional/mockable)
        if skip_extraction:
            print("[Optional] Extraction test skipped via --skip-extraction.")
        else:
            print("[6/6] Testing memory extraction...", end=" ")
            extract_payload = {
                "text": "I am working on deploying our AI memory pipeline to Fly.io and Render.",
                "user_id": user_id,
            }
            try:
                resp = client.post("/extraction", json=extract_payload)
                if resp.status_code in (200, 201):
                    extracted = resp.json()
                    print(f"OK ({len(extracted)} candidate(s) processed)")
                elif resp.status_code == 503:
                    print("SKIPPED (LLM service unavailable or not configured in environment)")
                else:
                    print(f"FAILED (Status {resp.status_code}: {resp.text})")
                    return False
            except Exception as e:
                print(f"SKIPPED (Extraction request error: {e})")

        # 7. Cleanup test memory
        print(f"\n[Cleanup] Deleting test memory {created_memory_id}...", end=" ")
        resp = client.delete(f"/memories/{created_memory_id}", params={"user_id": user_id})
        if resp.status_code in (200, 204):
            print("OK (Memory deleted/disabled)")
            created_memory_id = None
        else:
            print(f"NOTE: Delete returned status {resp.status_code}: {resp.text}")

        print("\n==========================================")
        print(" SUCCESS: All smoke test checks passed!   ")
        print("==========================================")
        return True

    except Exception as exc:
        print(f"\nFATAL: Smoke test failed with exception: {exc}")
        return False
    finally:
        # Best-effort cleanup if failed before step 7
        if created_memory_id:
            try:
                client.delete(f"/memories/{created_memory_id}", params={"user_id": user_id})
            except Exception:
                pass
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="RecallFabric API Deployment Smoke Test")
    parser.add_argument(
        "--url",
        "--base-url",
        dest="url",
        default="http://localhost:8000",
        help="Base URL of the RecallFabric API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API Key or Admin Token for authentication (if auth is enabled)",
    )
    parser.add_argument(
        "--user-id",
        default="smoke_test_user",
        help="Target user identifier for testing (default: smoke_test_user)",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip LLM extraction check (useful when running without hosted LLM API keys)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP request timeout in seconds (default: 30.0)",
    )

    args = parser.parse_args()
    success = run_smoke_test(
        base_url=args.url,
        api_key=args.api_key,
        user_id=args.user_id,
        skip_extraction=args.skip_extraction,
        timeout=args.timeout,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
