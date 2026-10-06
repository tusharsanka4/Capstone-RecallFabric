import httpx, json, sys

API = "http://127.0.0.1:11434/api/tags"
try:
    r = httpx.get(API, timeout=5.0)
    r.raise_for_status()
    data = r.json()
    print("[OK] Ollama is reachable. Available models:")
    for model in data.get('models', []):
        print(f"- {model.get('name')}")
except Exception as e:
    print(f"[FAIL] Failed to contact Ollama: {e}")
    sys.exit(1)
