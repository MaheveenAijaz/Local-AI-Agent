import requests
import socket
import sys

print("=" * 60)
print("DEBUGGING LOCAL AI AGENT")
print("=" * 60)

# Check Python version
print(f"Python version: {sys.version}")
print()

# Check if Ollama is reachable
print("Checking Ollama connection...")
try:
    response = requests.get("http://localhost:11434/api/tags", timeout=5)
    print(f"✅ Ollama is running on port 11434")
    print(f"   Response status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        models = data.get("models", [])
        print(f"   Available models: {len(models)} found")
        
        for i, model in enumerate(models):
            print(f"   {i+1}. {model['name']} ({model.get('size', 'N/A')} bytes)")
        
        # Check if qwen2.5:0.5b is available
        model_names = [m['name'] for m in models]
        if 'qwen2.5:0.5b' in model_names:
            print("✅ qwen2.5:0.5b is available")
        else:
            print("❌ qwen2.5:0.5b NOT found in models")
            print("   Please run: ollama pull qwen2.5:0.5b")
    else:
        print(f"❌ Ollama returned unexpected status: {response.status_code}")
        print(f"   Response: {response.text}")
        
except requests.exceptions.ConnectionError:
    print("❌ Cannot connect to Ollama at http://localhost:11434")
    print("   Make sure Ollama is running with: ollama serve")
except Exception as e:
    print(f"❌ Error connecting to Ollama: {e}")

print("\n" + "=" * 60)

# Test a simple chat with Ollama directly
print("Testing Ollama chat directly...")
try:
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen2.5:0.5b",
            "messages": [{"role": "user", "content": "Say hello in one word"}],
            "stream": False
        },
        timeout=30
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Ollama chat test successful!")
        print(f"   Response: {result['message']['content'][:100]}...")
    else:
        print(f"❌ Ollama returned status: {response.status_code}")
        print(f"   Response: {response.text[:200]}")
        
except requests.exceptions.Timeout:
    print("❌ Ollama timeout - model might be loading or slow")
except Exception as e:
    print(f"❌ Error testing Ollama: {e}")

print("\n" + "=" * 60)

# Test Flask app connection
print("Testing Flask app connection...")
try:
    response = requests.get("http://localhost:8080", timeout=5)
    print(f"✅ Flask app is running on port 8080")
    print(f"   Response status: {response.status_code}")
except requests.exceptions.ConnectionError:
    print("❌ Cannot connect to Flask app at http://localhost:8080")
    print("   Make sure you're running: python app.py")
except Exception as e:
    print(f"❌ Error connecting to Flask: {e}")

print("\n" + "=" * 60)

# Test the health check endpoint
print("Testing health check endpoint...")
try:
    response = requests.get("http://localhost:8080/api/check-ollama", timeout=5)
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Health check successful!")
        print(f"   Ollama running: {data.get('ollama_running')}")
        print(f"   Model available: {data.get('model_available')}")
        print(f"   Current model: {data.get('current_model')}")
        if not data.get('ollama_running'):
            print(f"   Error: {data.get('error')}")
    else:
        print(f"❌ Health check failed: {response.status_code}")
except Exception as e:
    print(f"❌ Error testing health check: {e}")

print("=" * 60)
print("\nTroubleshooting tips:")
print("1. If Ollama is not running: open new terminal and run 'ollama serve'")
print("2. If model is missing: run 'ollama pull qwen2.5:0.5b'")
print("3. If Flask is not running: run 'python app.py' in your project directory")
print("4. Check if firewall is blocking ports 8080 or 11434")
print("=" * 60)

input("\nPress Enter to exit...")