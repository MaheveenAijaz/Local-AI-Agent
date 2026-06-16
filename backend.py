# backend.py - UPDATED VERSION
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from pydantic import BaseModel
import requests
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
import json
from datetime import datetime

app = FastAPI(title="Local LLM Backend")

# Add CORS for your HTML frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],  # Your HTML server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_URL = "http://localhost:11434/api/generate"

# ========== OLD ENDPOINTS (for Streamlit/API) ==========
class Query(BaseModel):
    prompt: str
    model: str = "llama3.2"

@app.post("/ask")
def ask_ai(query: Query):
    """Simple text question endpoint"""
    try:
        payload = {
            "model": query.model,
            "prompt": query.prompt,
            "stream": False,
            "options": {"temperature": 0.7}
        }
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        return {"response": result.get("response", "").strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")

@app.post("/ask_with_file")
async def ask_with_file(prompt: str, file: UploadFile = File(None)):
    """Endpoint that accepts file uploads"""
    try:
        file_content = ""
        if file and file.content_type.startswith("text/"):
            file_content = (await file.read()).decode("utf-8")
        elif file:
            return {"error": "Only text files are supported"}
        
        full_prompt = f"""
        File content:
        {file_content[:5000]}
        
        User question: {prompt}
        
        Please provide a helpful answer based on the file content if provided.
        Answer:
        """
        
        payload = {
            "model": "llama3.2",
            "prompt": full_prompt,
            "stream": False,
            "options": {"temperature": 0.7}
        }
        
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        return {"response": result.get("response", "").strip()}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ========== NEW ENDPOINTS (for your HTML frontend) ==========
class ChatMessage(BaseModel):
    message: str
    user_id: str = None

@app.get("/api/health")
def health_check():
    """Health check endpoint for frontend"""
    try:
        # Check if Ollama is running
        response = requests.get("http://localhost:11434", timeout=2)
        ollama_status = "connected" if response.status_code == 200 else "disconnected"
        
        return {
            "status": "ok",
            "backend": "running",
            "ollama": ollama_status,
            "timestamp": datetime.now().isoformat()
        }
    except:
        return {
            "status": "ok",
            "backend": "running",
            "ollama": "disconnected",
            "timestamp": datetime.now().isoformat()
        }

@app.post("/api/chat")
async def chat_with_ai(chat: ChatMessage):
    """Chat endpoint for the HTML frontend"""
    try:
        # Prepare the prompt
        prompt = f"""
        You are a helpful AI assistant. The user said:
        
        "{chat.message}"
        
        Please respond in a friendly, helpful manner.
        Answer:
        """
        
        payload = {
            "model": "llama3.2",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9
            }
        }
        
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        return {
            "success": True,
            "response": result.get("response", "").strip(),
            "timestamp": datetime.now().isoformat()
        }
        
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Please start it with 'ollama serve'"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"status": "AI backend running", "ollama": "connected"}

if __name__ == "__main__":
    print("🚀 Starting AI Backend on http://localhost:8000")
    print("📡 Connect to Ollama at http://localhost:11434")
    print("🌐 HTML frontend should connect to http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)