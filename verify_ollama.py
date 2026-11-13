import sys

import httpx

api_url = "http://127.0.0.1:11434/api/tags"
try:
    response = httpx.get(api_url, timeout=5.0)
    response.raise_for_status()
    data = response.json()
    print("[OK] Ollama is reachable. Available models:")
    for model in data.get("models", []):
        print(f"- {model.get('name')}")
except Exception as e:
    print(f"[FAIL] Failed to contact Ollama: {e}")
    sys.exit(1)
