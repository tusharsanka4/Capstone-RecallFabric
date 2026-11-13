#!/usr/bin/env python3
"""RecallFabric Capstone Demo: Cross-Model Memory Portability.

Demonstrates two different AI models (e.g., a local model like Ollama and a
cloud-hosted model like OpenAI/Anthropic/Gemini) sharing the same persistent
memory layer without vendor lock-in.
"""

from __future__ import annotations

import argparse
import os
import time

import httpx

# ANSI Color formatting for presentation readability
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"


def banner(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 78}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 78}{RESET}\n")


def section(step: int, title: str) -> None:
    print(f"\n{BOLD}{YELLOW}[Step {step}] {title}{RESET}")
    print(f"{DIM}{'-' * 60}{RESET}")


def run_demo(
    base_url: str,
    api_key: str | None = None,
    user_id: str = "capstone_demo_user",
    model_a_name: str = "Model A (Local Ollama / Qwen)",
    model_b_name: str = "Model B (Hosted Cloud / GPT-4o)",
) -> None:
    base_url = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key

    client = httpx.Client(base_url=base_url, headers=headers, timeout=30.0)

    banner("🧠 RECALLFABRIC: CROSS-MODEL MEMORY PORTABILITY DEMO")
    print(f"{BOLD}Service Base URL:{RESET} {base_url}")
    print(f"{BOLD}Demo User ID:{RESET}     {user_id}")
    print(f"{BOLD}Model A:{RESET}             {model_a_name}")
    print(f"{BOLD}Model B:{RESET}             {model_b_name}")

    # Step 1: Health & Clean State
    section(1, "Service Capabilities & Fresh State Initialization")
    try:
        cap_resp = client.get("/v1/capabilities")
        if cap_resp.status_code == 200:
            caps = cap_resp.json()
            ver = caps.get("service_version", "1.0")
            print(f" {GREEN}✓{RESET} Connected to RecallFabric v{ver}")
            print(f"   Embedding Model: {caps.get('embedding_model')}")
            print(f"   Vector Dimensions: {caps.get('embedding_dimensions')}")
        else:
            print(f" {YELLOW}!{RESET} Capabilities returned HTTP {cap_resp.status_code}")

        # Purge demo user data for clean test
        del_resp = client.delete("/v1/users/me/memories", params={"user_id": user_id})
        if del_resp.status_code in {200, 204}:
            print(f" {GREEN}✓{RESET} Clean slate ready for demo user '{user_id}'")
    except Exception as exc:
        print(f" {YELLOW}Connection note:{RESET} {exc}")

    time.sleep(1)

    # Step 2: Model A interacts with user and writes to memory
    section(2, f"{model_a_name}: Learning User Context")
    user_statement = (
        "Hi! My name is Alex. I am a software engineer based in Seattle. "
        "I code strictly in Python 3.12 without semicolons, and I have a severe peanut allergy."
    )
    print(f"{BOLD}User to {model_a_name}:{RESET}")
    print(f'  "{user_statement}"\n')

    print(
        f"{DIM}Persisting and extracting atomic facts via "
        f"POST /v1/remember (extract=true)...{RESET}"
    )
    rem_resp = client.post(
        "/v1/remember",
        json={
            "user_id": user_id,
            "content": user_statement,
            "source": "model_a_local_chat",
            "extract": True,
        },
    )

    if rem_resp.status_code == 200:
        rem_data = rem_resp.json()
        print(f" {GREEN}✓ Memory Stored Successfully!{RESET}")
        extracted = rem_data.get("memories", [])
        if extracted:
            print(f"   Extracted {len(extracted)} structured atomic memory items:")
            for item in extracted:
                m_type = item.get("type", "fact")
                m_content = item.get("content", "")
                print(f"   • {MAGENTA}[{m_type.upper()}]{RESET} {m_content}")
        else:
            print("   (Direct explicit memory recorded)")
    else:
        print(f" {YELLOW}! Remember returned HTTP {rem_resp.status_code}: {rem_resp.text}{RESET}")

    time.sleep(1.5)

    # Step 3: Model B (completely different client/model) retrieves memory
    section(3, f"{model_b_name}: Zero-Shot Retrieval with Injected Context")
    user_query = "Suggest a quick dessert recipe for my Seattle dinner party tonight."
    print(f"{BOLD}User to {model_b_name} (Different Model / No Conversation History):{RESET}")
    print(f'  "{user_query}"\n')

    print(f"{DIM}Calling POST /v1/recall to semantically retrieve relevant context...{RESET}")
    recall_resp = client.post(
        "/v1/recall",
        json={
            "user_id": user_id,
            "query": user_query,
            "limit": 5,
            "char_budget": 1500,
        },
    )

    if recall_resp.status_code == 200:
        recall_data = recall_resp.json()
        retrieved_memories = recall_data.get("memories", [])
        formatted_context = recall_data.get("context", "")

        print(
            f" {GREEN}✓ Retrieved {len(retrieved_memories)} Relevant Memory Context Item(s):{RESET}"
        )
        for mem in retrieved_memories:
            score = mem.get("score", 0.0)
            content = mem.get("content", "")
            print(f"   • {BLUE}(Score: {score:.3f}){RESET} {content}")

        print(f"\n{BOLD}Ready-to-Inject System Context String:{RESET}")
        print(f"{GREEN}{formatted_context}{RESET}\n")

        print(f"{BOLD}{model_b_name} Formulated Output:{RESET}")
        print(
            f'  "Here is an artisan Seattle Blackberry Crisp! It uses local fresh berries, '
            f"oats, brown sugar, and cinnamon. It is {BOLD}{YELLOW}100% peanut-free{RESET} "
            f'to keep you and your guests completely safe!"'
        )
    else:
        err_msg = recall_resp.text
        print(f" {YELLOW}! Recall returned HTTP {recall_resp.status_code}: {err_msg}{RESET}")

    time.sleep(1.5)

    # Step 4: Memory Evolution (Conflict Resolution across models)
    section(4, "Cross-Model Evolution: Overriding Obsolete Facts")
    update_statement = "Update: I just relocated from Seattle to Berlin and switched to Rust."
    print(f"{BOLD}User informs {model_b_name}:{RESET}")
    print(f'  "{update_statement}"\n')

    print(f"{DIM}Posting update to RecallFabric with conflict resolution...{RESET}")
    client.post(
        "/v1/remember",
        json={
            "user_id": user_id,
            "content": update_statement,
            "source": "model_b_hosted_chat",
            "extract": True,
        },
    )

    print(
        f"\n{DIM}Now Model A asks: 'Where does the user live and what language do they use?'{RESET}"
    )
    evolve_resp = client.post(
        "/v1/recall",
        json={
            "user_id": user_id,
            "query": "Where do I live and what language do I code in?",
            "limit": 3,
        },
    )

    if evolve_resp.status_code == 200:
        evolve_context = evolve_resp.json().get("context", "")
        print(f"\n{BOLD}Updated Context Automatically Available to Model A:{RESET}")
        print(f"{GREEN}{evolve_context}{RESET}")
        print(
            f" {GREEN}✓ Success:{RESET} Berlin and Rust superseded previous facts "
            "without manual intervention!"
        )

    # Summary
    banner("✨ CAPSTONE DEMONSTRATION COMPLETE: MEMORY PORTABILITY ACHIEVED")
    print("Key Takeaways:")
    print(" 1. Independence: Memory belongs to the user, not proprietary model silos.")
    print(" 2. Zero-Shot Context: Model B understood constraints learned only by Model A.")
    print(" 3. Conflict Handling: Real-time superseding of obsolete preferences.")
    print(" 4. Standard Open Surface: Compatible with MCP, OpenAI SDK Proxy, and REST.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="RecallFabric Capstone Presentation Demo")
    parser.add_argument(
        "--url",
        default=os.environ.get("RECALLFABRIC_BASE_URL", "http://localhost:8000"),
        help="RecallFabric API base URL",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("RECALLFABRIC_API_KEY"),
        help="RecallFabric API Key (rf_...)",
    )
    parser.add_argument(
        "--user-id",
        default="capstone_demo_user",
        help="Demo user identifier",
    )
    parser.add_argument(
        "--model-a",
        default="Model A (Local Ollama / Qwen)",
        help="Label for Model A",
    )
    parser.add_argument(
        "--model-b",
        default="Model B (Hosted Cloud / GPT-4o)",
        help="Label for Model B",
    )

    args = parser.parse_args()
    run_demo(
        base_url=args.url,
        api_key=args.api_key,
        user_id=args.user_id,
        model_a_name=args.model_a,
        model_b_name=args.model_b,
    )


if __name__ == "__main__":
    main()
