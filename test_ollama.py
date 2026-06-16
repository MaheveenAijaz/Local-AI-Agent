import requests

try:
    # Test Ollama connection
    response = requests.get("http://localhost:11434/api/tags")
    if response.status_code == 200:
        print("✅ Ollama is running!")
        models = response.json().get("models", [])
        if models:
            print(f"Available models: {[m['name'] for m in models]}")
        else:
            print("No models found. Run: ollama pull qwen2.5:0.5b")
    else:
        print(f"❌ Ollama returned status: {response.status_code}")
except requests.exceptions.ConnectionError:
    print("❌ Cannot connect to Ollama. Make sure it's running with 'ollama serve'")