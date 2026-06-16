from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import uuid
import requests
import logging
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import PyPDF2
import docx

# -------------------------------
# Logging
# -------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------
# Flask Setup
# -------------------------------
app = Flask(__name__, static_folder="frontend", static_url_path="")
CORS(app, supports_credentials=True)
app.secret_key = "local-offline-secret-key"

# -------------------------------
# Config
# -------------------------------
UPLOAD_FOLDER = "uploads"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:0.5b"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SYSTEM_PROMPT = """You are a smart offline AI assistant.

Rules:
- Give clear, correct answers
- Use document if helpful
- If unsure, say: Based on my general knowledge...
- Keep answers simple and useful
"""

# -------------------------------
# Database
# -------------------------------
def get_db():
    return sqlite3.connect("local_agent.db", check_same_thread=False)

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                name TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

init_db()

# -------------------------------
# CHECK OLLAMA
# -------------------------------
@app.route("/api/check-ollama", methods=["GET"])
def check_ollama():
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = [m["name"] for m in res.json().get("models", [])]

        return jsonify({
            "ollama_running": True,
            "model_available": OLLAMA_MODEL in models,
            "models": models
        })
    except:
        return jsonify({"ollama_running": False})

# -------------------------------
# DOCUMENT PARSER
# -------------------------------
def parse_document(path, name):
    ext = name.split(".")[-1].lower()
    try:
        if ext == "txt":
            return open(path, "r", encoding="utf-8").read()

        elif ext == "pdf":
            reader = PyPDF2.PdfReader(path)
            return "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])

        elif ext == "docx":
            doc = docx.Document(path)
            return "\n".join([p.text for p in doc.paragraphs])

    except Exception as e:
        logger.error(e)

    return ""

# -------------------------------
# FRONTEND
# -------------------------------
@app.route("/")
def index():
    return send_from_directory("frontend", "login.html")

@app.route("/<path:path>")
def serve_frontend(path):
    if os.path.exists(os.path.join("frontend", path)):
        return send_from_directory("frontend", path)
    return send_from_directory("frontend", "login.html")

# -------------------------------
# AUTH
# -------------------------------
@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (data["username"], generate_password_hash(data["password"]))
            )
            conn.commit()
        return jsonify({"success": True})
    except:
        return jsonify({"error": "Username exists"}), 409

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (data["username"],)
        ).fetchone()

    if not user or not check_password_hash(user[2], data["password"]):
        return jsonify({"error": "Invalid credentials"}), 401

    return jsonify({"success": True, "user_id": user[0]})

# -------------------------------
# UPLOAD
# -------------------------------
@app.route("/api/upload", methods=["POST"])
def upload():
    user_id = request.headers.get("X-USER-ID")
    file = request.files.get("file")

    if not user_id or not file:
        return jsonify({"error": "Invalid"}), 400

    filename = secure_filename(file.filename)
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)

    text = parse_document(path, filename)

    with get_db() as conn:
        conn.execute(
            "INSERT INTO files (id, user_id, name, content) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, filename, text[:4000])
        )
        conn.commit()

    os.remove(path)
    return jsonify({"success": True})

# -------------------------------
# CHAT (FINAL)
# -------------------------------
@app.route("/api/chat", methods=["POST"])
def chat():
    user_id = request.headers.get("X-USER-ID")
    data = request.json
    user_input = data.get("message")

    if not user_id or not user_input:
        return jsonify({"error": "Invalid request"}), 400

    # Get history + document
    with get_db() as conn:
        history = conn.execute(
            "SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 2",
            (user_id,)
        ).fetchall()

        docs = conn.execute(
            "SELECT content FROM files WHERE user_id=? LIMIT 1",
            (user_id,)
        ).fetchall()

    context = docs[0][0][:1200] if docs else ""

    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for h in reversed(history):
        messages.append({"role": h[0], "content": h[1]})

    # Add context
    if context:
        messages.append({
            "role": "system",
            "content": f"Document:\n{context}"
        })

    # Smart query handling
    if "summarize" in user_input.lower():
        messages.append({
            "role": "user",
            "content": f"Summarize this document in simple words:\n\n{context}"
        })

    elif "explain" in user_input.lower():
        messages.append({
            "role": "user",
            "content": f"Explain this simply:\n\n{context}"
        })

    elif context:
        messages.append({
            "role": "user",
            "content": f"""
Use document if helpful.

Document:
{context}

Question:
{user_input}
"""
        })

    else:
        messages.append({
            "role": "user",
            "content": user_input
        })

    # Call Ollama
    try:
        res = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_predict": 60,
                    "temperature": 0.5,
                    "top_k": 20,
                    "top_p": 0.9
                }
            },
            timeout=60
        )

        data = res.json()
        ai_msg = data.get("message", {}).get("content", "Error generating response")

        # Save messages (FIXED DB ERROR)
        with get_db() as conn:
            conn.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, "user", user_input)
            )
            conn.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, "assistant", ai_msg)
            )
            conn.commit()

        return jsonify({"success": True, "response": ai_msg})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------------
# RUN
# -------------------------------
if __name__ == "__main__":
    print("🚀 Running Local AI Agent...")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)