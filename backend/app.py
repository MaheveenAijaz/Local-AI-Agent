from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
import sqlite3
import os
import hashlib
import json
import uuid
import requests
from datetime import datetime
from werkzeug.utils import secure_filename
import logging
import PyPDF2
import docx

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=["http://127.0.0.1:8080", "http://localhost:8080"])
app.secret_key = 'local-ai-agent-secret-key-2024'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Constants
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'png', 'jpg', 'jpeg'}
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:0.5b"

# Create upload folder
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Simple system prompt for natural conversation
SYSTEM_PROMPT = """You are a friendly AI assistant. Be helpful, natural, and conversational.
- If someone says "hi", "hello", or "hey", greet them warmly like "Hello! How can I help you today?"
- Answer questions based on the context provided from uploaded documents
- If no context is provided, use your general knowledge
- Keep responses concise but helpful
- Be enthusiastic and engaging"""

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_file(filepath, filename):
    """Extract text from uploaded files"""
    ext = filename.rsplit('.', 1)[1].lower()
    
    try:
        if ext == 'txt':
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        
        elif ext == 'pdf':
            text = ""
            with open(filepath, 'rb') as f:
                pdf = PyPDF2.PdfReader(f)
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            return text
        
        elif ext == 'docx':
            doc = docx.Document(filepath)
            return "\n".join([p.text for p in doc.paragraphs])
        
        else:
            return f"[{ext.upper()} file uploaded: {filename}]"
    
    except Exception as e:
        logger.error(f"Error extracting text: {e}")
        return f"Could not extract text from {filename}"

# Create demo user with email field
def create_demo_user():
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        
        # Check if demo user exists
        c.execute("SELECT * FROM users WHERE username = 'demo'")
        existing = c.fetchone()
        
        if existing:
            logger.info("Demo user already exists")
        else:
            # Insert demo user with placeholder email
            c.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                      ('demo', 'demo@example.com', hash_password('demo123')))
            conn.commit()
            logger.info("Demo user created: demo / demo123")
        
        conn.close()
    except Exception as e:
        logger.error(f"Error creating demo user: {e}")

create_demo_user()

# ==================== AUTH ENDPOINTS ====================

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()
        
        if user and user[2] == hash_password(password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            return jsonify({"success": True, "user": {"id": user[0], "username": user[1]}})
        
        return jsonify({"success": False, "error": "Invalid credentials"}), 401
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        username = data.get('username')
        email = data.get('email', f"{username}@example.com")  # Default email if not provided
        password = data.get('password')
        
        if len(username) < 3 or len(password) < 6:
            return jsonify({"success": False, "error": "Username min 3 chars, password min 6 chars"}), 400
        
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        
        try:
            c.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                      (username, email, hash_password(password)))
            user_id = c.lastrowid
            conn.commit()
            
            session['user_id'] = user_id
            session['username'] = username
            
            return jsonify({"success": True, "user": {"id": user_id, "username": username}})
        
        except sqlite3.IntegrityError as e:
            if "username" in str(e):
                return jsonify({"success": False, "error": "Username already exists"}), 409
            else:
                return jsonify({"success": False, "error": "Email already registered"}), 409
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Signup error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    if 'user_id' in session:
        return jsonify({"authenticated": True, "user": {"id": session['user_id'], "username": session['username']}})
    return jsonify({"authenticated": False})

# ==================== FILE UPLOAD ====================

@app.route('/api/files/upload', methods=['POST'])
def upload_file():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "error": "No file selected"}), 400
        
        if not allowed_file(file.filename):
            return jsonify({"success": False, "error": "File type not allowed"}), 400
        
        # Save file
        file_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, f"{file_id}_{filename}")
        file.save(filepath)
        
        # Extract text
        content = extract_text_from_file(filepath, filename)
        
        # Save to database
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        
        # Check if files table exists, if not create it
        c.execute('''CREATE TABLE IF NOT EXISTS files
                     (id TEXT PRIMARY KEY,
                      user_id INTEGER,
                      filename TEXT,
                      filepath TEXT,
                      content TEXT,
                      uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        c.execute("INSERT INTO files (id, user_id, filename, filepath, content) VALUES (?, ?, ?, ?, ?)",
                  (file_id, session['user_id'], filename, filepath, content[:5000]))  # Store preview
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "file": {
                "id": file_id,
                "filename": filename,
                "uploaded_at": datetime.now().isoformat()
            }
        })
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/files', methods=['GET'])
def get_files():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        
        # Create files table if it doesn't exist
        c.execute('''CREATE TABLE IF NOT EXISTS files
                     (id TEXT PRIMARY KEY,
                      user_id INTEGER,
                      filename TEXT,
                      filepath TEXT,
                      content TEXT,
                      uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        c.execute("SELECT id, filename, uploaded_at FROM files WHERE user_id = ? ORDER BY uploaded_at DESC",
                  (session['user_id'],))
        files = [{"id": r[0], "filename": r[1], "uploaded_at": r[2]} for r in c.fetchall()]
        conn.close()
        
        return jsonify({"success": True, "files": files})
    except Exception as e:
        logger.error(f"Get files error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/files/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT filepath FROM files WHERE id = ? AND user_id = ?", (file_id, session['user_id']))
        result = c.fetchone()
        
        if result:
            # Delete physical file
            try:
                if os.path.exists(result[0]):
                    os.remove(result[0])
            except:
                pass
            
            # Delete from database
            c.execute("DELETE FROM files WHERE id = ?", (file_id,))
            conn.commit()
        
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== CHAT ENDPOINT ====================

@app.route('/api/chat', methods=['POST'])
def chat():
    """Simple, reliable chat endpoint"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        data = request.json
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({"success": False, "error": "Message required"}), 400
        
        logger.info(f"User {session['username']} says: {user_message}")
        
        # Save user message
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        
        # Create messages table if it doesn't exist
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      role TEXT,
                      content TEXT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                  (session['user_id'], 'user', user_message))
        conn.commit()
        
        # Get recent conversation history (last 5 messages)
        c.execute("""SELECT role, content FROM messages 
                     WHERE user_id = ? 
                     ORDER BY timestamp DESC LIMIT 5""", (session['user_id'],))
        history = list(reversed(c.fetchall()))  # Reverse to get chronological order
        
        # Get relevant file content if available
        c.execute("SELECT filename, content FROM files WHERE user_id = ? LIMIT 3", (session['user_id'],))
        files = c.fetchall()
        conn.close()
        
        # Prepare context from files
        file_context = ""
        if files:
            file_context = "Here are excerpts from your uploaded documents:\n\n"
            for filename, content in files:
                if content and len(content) > 50:
                    file_context += f"From '{filename}':\n{content[:500]}...\n\n"
        
        # Prepare messages for Ollama
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        
        # Add conversation history
        for role, content in history:
            messages.append({"role": role, "content": content})
        
        # Add file context if available and message isn't just a simple greeting
        simple_greetings = ['hi', 'hello', 'hey', 'hi there', 'hello there', 'hey there']
        if file_context and user_message.lower() not in simple_greetings:
            messages.append({"role": "system", "content": file_context})
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        logger.info(f"Sending {len(messages)} messages to Ollama")
        
        # Call Ollama
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.7
                }
            },
            timeout=60
        )
        
        if response.status_code == 200:
            ai_response = response.json()['message']['content']
            logger.info(f"AI response: {ai_response[:100]}...")
            
            # Save AI response
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                      (session['user_id'], 'assistant', ai_response))
            conn.commit()
            conn.close()
            
            return jsonify({
                "success": True,
                "response": ai_response
            })
        else:
            logger.error(f"Ollama error: {response.status_code}")
            return jsonify({
                "success": False,
                "error": "AI model error. Make sure Ollama is running."
            }), 500
            
    except requests.exceptions.ConnectionError:
        logger.error("Cannot connect to Ollama")
        return jsonify({
            "success": False,
            "error": "Cannot connect to Ollama. Please run 'ollama serve' first."
        }), 503
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ==================== CHAT HISTORY ====================

@app.route('/api/history', methods=['GET'])
def get_history():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        
        # Create messages table if it doesn't exist
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      role TEXT,
                      content TEXT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        c.execute("""SELECT role, content, timestamp FROM messages 
                     WHERE user_id = ? 
                     ORDER BY timestamp ASC LIMIT 50""", (session['user_id'],))
        messages = [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in c.fetchall()]
        conn.close()
        
        return jsonify({"success": True, "messages": messages})
    except Exception as e:
        logger.error(f"History error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE user_id = ?", (session['user_id'],))
        conn.commit()
        conn.close()
        
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Clear history error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health():
    ollama_status = False
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        ollama_status = r.status_code == 200
    except:
        pass
    
    return jsonify({
        "success": True,
        "status": "healthy",
        "ollama": ollama_status,
        "authenticated": 'user_id' in session,
        "user": session.get('username')
    })

# ==================== FRONTEND ROUTES ====================

@app.route('/')
def login_page():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Local AI Assistant - Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .container {
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                padding: 40px;
                width: 90%;
                max-width: 400px;
            }
            h1 { color: #333; margin-bottom: 10px; font-size: 28px; }
            .subtitle { color: #666; margin-bottom: 30px; font-size: 14px; }
            .input-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 5px; color: #555; font-weight: 500; }
            input {
                width: 100%;
                padding: 12px 15px;
                border: 2px solid #e0e0e0;
                border-radius: 10px;
                font-size: 16px;
                transition: border-color 0.3s;
            }
            input:focus { outline: none; border-color: #667eea; }
            .btn {
                width: 100%;
                padding: 14px;
                background: #667eea;
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: background 0.3s;
                margin-bottom: 10px;
            }
            .btn:hover { background: #5a67d8; }
            .btn-secondary { background: #48bb78; }
            .btn-secondary:hover { background: #38a169; }
            .result {
                margin-top: 20px;
                padding: 10px;
                border-radius: 10px;
                display: none;
            }
            .result.error {
                background: #fed7d7;
                color: #c53030;
                display: block;
            }
            .result.success {
                background: #c6f6d5;
                color: #22543d;
                display: block;
            }
            .demo-note {
                margin-top: 20px;
                padding: 15px;
                background: #f7fafc;
                border-radius: 10px;
                font-size: 14px;
                color: #4a5568;
            }
            .demo-note strong { color: #667eea; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Local AI Assistant</h1>
            <p class="subtitle">Private • Secure • 100% Local</p>
            
            <div class="input-group">
                <label>Username</label>
                <input type="text" id="username" placeholder="Enter username" value="demo">
            </div>
            
            <div class="input-group">
                <label>Password</label>
                <input type="password" id="password" placeholder="Enter password" value="demo123">
            </div>
            
            <button class="btn" onclick="login()">Login</button>
            <button class="btn btn-secondary" onclick="showSignup()">Create New Account</button>
            
            <div id="result" class="result"></div>
            
            <div class="demo-note">
                <strong>📝 Demo Account:</strong><br>
                Username: demo<br>
                Password: demo123
            </div>
        </div>
        
        <script>
            async function login() {
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                const resultDiv = document.getElementById('result');
                
                try {
                    const response = await fetch('/api/login', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({username, password})
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        resultDiv.className = 'result success';
                        resultDiv.textContent = 'Login successful! Redirecting...';
                        setTimeout(() => { window.location.href = '/chat'; }, 1000);
                    } else {
                        resultDiv.className = 'result error';
                        resultDiv.textContent = data.error || 'Login failed';
                    }
                } catch (error) {
                    resultDiv.className = 'result error';
                    resultDiv.textContent = 'Error: ' + error.message;
                }
            }
            
            function showSignup() {
                const username = prompt('Enter username (min 3 chars):');
                if (!username) return;
                
                const password = prompt('Enter password (min 6 chars):');
                if (!password) return;
                
                signup(username, password);
            }
            
            async function signup(username, password) {
                const resultDiv = document.getElementById('result');
                
                try {
                    const response = await fetch('/api/signup', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({username, password})
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        resultDiv.className = 'result success';
                        resultDiv.textContent = 'Account created! Logging in...';
                        setTimeout(() => { window.location.href = '/chat'; }, 1000);
                    } else {
                        resultDiv.className = 'result error';
                        resultDiv.textContent = data.error || 'Signup failed';
                    }
                } catch (error) {
                    resultDiv.className = 'result error';
                    resultDiv.textContent = 'Error: ' + error.message;
                }
            }
            
            // Auto login on Enter key
            document.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') login();
            });
        </script>
    </body>
    </html>
    '''

@app.route('/chat')
def chat_page():
    # Simple HTML page - authentication will be checked via API
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Local AI Chat</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #f0f2f5;
                height: 100vh;
                display: flex;
                flex-direction: column;
            }
            .header {
                background: white;
                padding: 15px 30px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .header h2 { color: #333; font-size: 20px; }
            .header h2 span { color: #667eea; }
            .logout-btn {
                background: #f56565;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 8px;
                cursor: pointer;
                font-size: 14px;
            }
            .logout-btn:hover { background: #e53e3e; }
            .main-container {
                display: flex;
                flex: 1;
                overflow: hidden;
            }
            .sidebar {
                width: 280px;
                background: white;
                border-right: 1px solid #e0e0e0;
                display: flex;
                flex-direction: column;
                padding: 20px;
            }
            .sidebar h3 { color: #555; margin-bottom: 15px; font-size: 16px; }
            .upload-area {
                background: #f7fafc;
                border: 2px dashed #cbd5e0;
                border-radius: 10px;
                padding: 20px;
                text-align: center;
                margin-bottom: 20px;
            }
            .upload-btn {
                background: #667eea;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 8px;
                cursor: pointer;
                font-size: 14px;
                margin-top: 10px;
                width: 100%;
            }
            .upload-btn:hover { background: #5a67d8; }
            .files-list {
                flex: 1;
                overflow-y: auto;
            }
            .file-item {
                background: #f7fafc;
                padding: 12px;
                border-radius: 8px;
                margin-bottom: 10px;
                font-size: 14px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .file-name {
                color: #2d3748;
                max-width: 160px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .delete-file {
                color: #f56565;
                cursor: pointer;
                font-size: 18px;
                padding: 0 5px;
            }
            .delete-file:hover { color: #e53e3e; }
            .chat-container {
                flex: 1;
                display: flex;
                flex-direction: column;
                background: white;
            }
            .messages-area {
                flex: 1;
                overflow-y: auto;
                padding: 30px;
                background: #f8fafc;
            }
            .message {
                margin-bottom: 20px;
                max-width: 70%;
                clear: both;
            }
            .message.user { float: right; }
            .message.assistant { float: left; }
            .message-content {
                padding: 12px 18px;
                border-radius: 18px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                word-wrap: break-word;
            }
            .user .message-content {
                background: #667eea;
                color: white;
                border-bottom-right-radius: 4px;
            }
            .assistant .message-content {
                background: white;
                color: #333;
                border-bottom-left-radius: 4px;
            }
            .message-time {
                font-size: 11px;
                color: #999;
                margin-top: 5px;
                text-align: right;
            }
            .input-area {
                background: white;
                padding: 20px 30px;
                border-top: 1px solid #e0e0e0;
                display: flex;
                gap: 10px;
            }
            .message-input {
                flex: 1;
                padding: 12px 18px;
                border: 2px solid #e0e0e0;
                border-radius: 25px;
                font-size: 16px;
            }
            .message-input:focus {
                outline: none;
                border-color: #667eea;
            }
            .send-btn {
                background: #667eea;
                color: white;
                border: none;
                width: 50px;
                height: 50px;
                border-radius: 25px;
                cursor: pointer;
                font-size: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .send-btn:hover { background: #5a67d8; }
            .status {
                position: fixed;
                bottom: 20px;
                right: 20px;
                background: #48bb78;
                color: white;
                padding: 8px 16px;
                border-radius: 20px;
                font-size: 14px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .status.error { background: #f56565; }
            @media (max-width: 768px) {
                .sidebar { display: none; }
                .message { max-width: 85%; }
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h2>🤖 <span>Local AI</span> Assistant</h2>
            <button class="logout-btn" onclick="logout()">Logout</button>
        </div>
        
        <div class="main-container">
            <div class="sidebar">
                <h3>📁 Your Documents</h3>
                <div class="upload-area">
                    <input type="file" id="fileInput" style="display: none;" onchange="uploadFile()">
                    <p style="color: #718096; margin-bottom: 10px;">Upload PDF, DOCX, or TXT</p>
                    <button class="upload-btn" onclick="document.getElementById('fileInput').click()">
                        Choose File
                    </button>
                </div>
                <div id="filesList" class="files-list">
                    <p style="color: #a0aec0; text-align: center;">No files uploaded yet</p>
                </div>
            </div>
            
            <div class="chat-container">
                <div id="messagesArea" class="messages-area"></div>
                
                <div class="input-area">
                    <input type="text" id="messageInput" class="message-input" 
                           placeholder="Type your message..." onkeypress="if(event.key==='Enter') sendMessage()">
                    <button class="send-btn" onclick="sendMessage()">➤</button>
                </div>
            </div>
        </div>
        
        <div id="status" class="status">Connected</div>
        
        <script>
            let messageInterval;
            
            // Check authentication on load
            async function checkAuth() {
                const res = await fetch('/api/auth/check');
                const data = await res.json();
                if (!data.authenticated) {
                    window.location.href = '/';
                }
            }
            checkAuth();
            
            // Load messages
            async function loadMessages() {
                try {
                    const res = await fetch('/api/history');
                    const data = await res.json();
                    if (data.success) {
                        const messagesArea = document.getElementById('messagesArea');
                        messagesArea.innerHTML = '';
                        data.messages.forEach(msg => {
                            addMessageToUI(msg.role, msg.content, msg.timestamp);
                        });
                        scrollToBottom();
                    }
                } catch (error) {
                    console.error('Error loading messages:', error);
                }
            }
            
            // Load files
            async function loadFiles() {
                try {
                    const res = await fetch('/api/files');
                    const data = await res.json();
                    if (data.success) {
                        const filesList = document.getElementById('filesList');
                        if (data.files.length === 0) {
                            filesList.innerHTML = '<p style="color: #a0aec0; text-align: center;">No files uploaded yet</p>';
                        } else {
                            filesList.innerHTML = data.files.map(file => `
                                <div class="file-item">
                                    <span class="file-name" title="${file.filename}">📄 ${file.filename}</span>
                                    <span class="delete-file" onclick="deleteFile('${file.id}')">×</span>
                                </div>
                            `).join('');
                        }
                    }
                } catch (error) {
                    console.error('Error loading files:', error);
                }
            }
            
            // Send message
            async function sendMessage() {
                const input = document.getElementById('messageInput');
                const message = input.value.trim();
                if (!message) return;
                
                input.value = '';
                setStatus('thinking', 'Thinking...');
                
                // Add to UI immediately
                addMessageToUI('user', message, new Date().toISOString());
                
                try {
                    const res = await fetch('/api/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({message})
                    });
                    
                    const data = await res.json();
                    if (data.success) {
                        addMessageToUI('assistant', data.response, new Date().toISOString());
                        setStatus('connected', 'Connected');
                    } else {
                        addMessageToUI('system', 'Error: ' + data.error, new Date().toISOString());
                        setStatus('error', 'Error');
                    }
                } catch (error) {
                    addMessageToUI('system', 'Error: ' + error.message, new Date().toISOString());
                    setStatus('error', 'Error');
                }
                
                scrollToBottom();
            }
            
            // Upload file
            async function uploadFile() {
                const fileInput = document.getElementById('fileInput');
                const file = fileInput.files[0];
                if (!file) return;
                
                const formData = new FormData();
                formData.append('file', file);
                
                setStatus('thinking', 'Uploading...');
                
                try {
                    const res = await fetch('/api/files/upload', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const data = await res.json();
                    if (data.success) {
                        addMessageToUI('system', '📄 File uploaded: ' + file.name, new Date().toISOString());
                        loadFiles();
                        setStatus('connected', 'Connected');
                    } else {
                        setStatus('error', 'Upload failed');
                        alert('Error: ' + data.error);
                    }
                } catch (error) {
                    setStatus('error', 'Error');
                    alert('Error: ' + error.message);
                }
                
                fileInput.value = '';
            }
            
            // Delete file
            async function deleteFile(fileId) {
                if (!confirm('Delete this file?')) return;
                
                try {
                    const res = await fetch('/api/files/' + fileId, {
                        method: 'DELETE'
                    });
                    
                    const data = await res.json();
                    if (data.success) {
                        loadFiles();
                        addMessageToUI('system', 'File deleted', new Date().toISOString());
                    }
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }
            
            // Helper: Add message to UI
            function addMessageToUI(role, content, timestamp) {
                const messagesArea = document.getElementById('messagesArea');
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${role}`;
                
                const time = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
                
                messageDiv.innerHTML = `
                    <div class="message-content">${escapeHtml(content)}</div>
                    <div class="message-time">${time}</div>
                `;
                
                messagesArea.appendChild(messageDiv);
            }
            
            // Helper: Escape HTML
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            
            // Helper: Scroll to bottom
            function scrollToBottom() {
                const messagesArea = document.getElementById('messagesArea');
                messagesArea.scrollTop = messagesArea.scrollHeight;
            }
            
            // Helper: Set status
            function setStatus(type, message) {
                const statusDiv = document.getElementById('status');
                statusDiv.className = 'status ' + (type === 'error' ? 'error' : '');
                statusDiv.textContent = message;
            }
            
            // Logout
            async function logout() {
                await fetch('/api/logout', {method: 'POST'});
                window.location.href = '/';
            }
            
            // Initial load
            loadMessages();
            loadFiles();
            
            // Auto-refresh messages every 3 seconds
            messageInterval = setInterval(loadMessages, 3000);
            
            // Clean up interval on page unload
            window.addEventListener('beforeunload', function() {
                if (messageInterval) clearInterval(messageInterval);
            });
        </script>
    </body>
    </html>
    '''

# ==================== RUN ====================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🤖 LOCAL AI ASSISTANT - FIXED VERSION")
    print("="*60)
    print("\n✅ FIXED: Email field issue resolved")
    print("\n✅ FEATURES:")
    print("   • Natural conversation - responds to greetings")
    print("   • Document upload & analysis")
    print("   • File support: PDF, DOCX, TXT")
    print("   • Chat history")
    print("   • Demo account ready")
    print("\n🚀 ACCESS:")
    print("   • Login: http://127.0.0.1:8080")
    print("   • Demo: demo / demo123")
    print("\n📋 QUICK START:")
    print("   1. Make sure Ollama is running: ollama serve")
    print("   2. Pull model: ollama pull qwen2.5:0.5b")
    print("   3. Run: python app.py")
    print("   4. Open: http://127.0.0.1:8080")
    print("\n🔍 TEST IT:")
    print("   • Say 'hi' - should greet you warmly")
    print("   • Upload a document - ask questions about it")
    print("   • Have a normal conversation")
    print("="*60 + "\n")
    
    # Check Ollama
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        if r.status_code == 200:
            models = r.json().get('models', [])
            print("✅ Ollama is running")
            if models:
                print(f"   Available models: {[m['name'] for m in models]}")
            else:
                print("   ⚠️  No models found. Pull one: ollama pull qwen2.5:0.5b")
        else:
            print("⚠️  Ollama not responding properly")
    except:
        print("⚠️  Ollama not running - start with: ollama serve")
    
    print("\n🚀 Server starting at http://127.0.0.1:8080")
    app.run(host='127.0.0.1', port=8080, debug=True)