from flask import Flask, request, jsonify, send_file, session
from flask_cors import CORS
import sqlite3
import os
import hashlib
import json
import uuid
import requests
from datetime import datetime
import chromadb
from chromadb.utils import embedding_functions
import PyPDF2
import docx    
import csv
import io
import mimetypes
from werkzeug.utils import secure_filename
import logging
import base64
from PIL import Image
import pytesseract
import pdf2image
import re  # Added for message cleaning

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=["http://127.0.0.1:8080", "http://localhost:8080"])
app.secret_key = 'local-ai-agent-secret-key-2024'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour

# Constants
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'csv', 'json', 'md', 'rtf', 'png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'}
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:0.5b"  # Default model

# ✅ UPDATED SYSTEM PROMPT - Simple and direct
SYSTEM_PROMPT = """You are a helpful AI assistant. Respond naturally to users.
When users say "hi" or "hello", respond with a friendly greeting.
Answer questions helpfully and directly.
Do NOT mention search results or patterns unless the user specifically asks for search results.
Always respond as if you're having a normal conversation."""

# Initialize directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('chroma_db', exist_ok=True)

# Set Tesseract path for Windows
try:
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except:
    pass  # Use system PATH if not Windows or different location

# Initialize SQLite database
def init_db():
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE NOT NULL,
                      email TEXT UNIQUE NOT NULL,
                      password_hash TEXT NOT NULL,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      last_login TIMESTAMP)''')
        
        # Chat sessions table
        c.execute('''CREATE TABLE IF NOT EXISTS chat_sessions
                     (id TEXT PRIMARY KEY,
                      user_id INTEGER,
                      title TEXT,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      is_active BOOLEAN DEFAULT 1,
                      FOREIGN KEY (user_id) REFERENCES users (id))''')
        
        # Messages table
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      session_id TEXT,
                      role TEXT CHECK(role IN ('user', 'assistant', 'system')),
                      content TEXT,
                      tokens INTEGER DEFAULT 0,
                      timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (session_id) REFERENCES chat_sessions (id))''')
        
        # Uploaded files table
        c.execute('''CREATE TABLE IF NOT EXISTS uploaded_files
                     (id TEXT PRIMARY KEY,
                      user_id INTEGER,
                      original_filename TEXT,
                      stored_filename TEXT,
                      file_type TEXT,
                      file_size INTEGER,
                      uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      processed BOOLEAN DEFAULT 0,
                      chunk_count INTEGER DEFAULT 0,
                      FOREIGN KEY (user_id) REFERENCES users (id))''')
        
        # File chunks table
        c.execute('''CREATE TABLE IF NOT EXISTS file_chunks
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      file_id TEXT,
                      chunk_index INTEGER,
                      chunk_text TEXT,
                      embedding_id TEXT,
                      FOREIGN KEY (file_id) REFERENCES uploaded_files (id))''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")

init_db()

# Initialize ChromaDB
def init_chromadb():
    try:
        chroma_client = chromadb.PersistentClient(path="chroma_db")
        
        # Check if sentence_transformers is available
        try:
            import sentence_transformers
            # Create embedding function
            embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            
            # Create or get collections
            try:
                documents_collection = chroma_client.get_collection(
                    name="documents",
                    embedding_function=embedding_function
                )
                logger.info("✅ Loaded existing ChromaDB collection")
            except:
                documents_collection = chroma_client.create_collection(
                    name="documents",
                    embedding_function=embedding_function,
                    metadata={"hnsw:space": "cosine"}
                )
                logger.info("✅ Created new ChromaDB collection")
            
            return chroma_client, documents_collection
        except ImportError:
            logger.warning("⚠️  sentence_transformers not installed. Using default embedding function.")
            # Use default embedding function
            embedding_function = embedding_functions.DefaultEmbeddingFunction()
            
            try:
                documents_collection = chroma_client.get_collection(
                    name="documents",
                    embedding_function=embedding_function
                )
                logger.info("✅ Loaded existing ChromaDB collection (default)")
            except:
                documents_collection = chroma_client.create_collection(
                    name="documents",
                    embedding_function=embedding_function,
                    metadata={"hnsw:space": "cosine"}
                )
                logger.info("✅ Created new ChromaDB collection (default)")
            
            return chroma_client, documents_collection
            
    except Exception as e:
        logger.error(f"❌ ChromaDB initialization failed: {e}")
        return None, None

chroma_client, chroma_collection = init_chromadb()

def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    """Verify password against hash"""
    return hash_password(password) == password_hash

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_image_file(filename):
    """Check if file is an image"""
    image_extensions = {'png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in image_extensions

def extract_text_from_file(filepath, file_type):
    """Extract text from various file formats"""
    try:
        if file_type == 'txt' or file_type == 'md' or file_type == 'rtf':
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        
        elif file_type == 'pdf':
            text = ""
            with open(filepath, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page_num, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"--- Page {page_num + 1} ---\n{page_text}\n\n"
            return text
        
        elif file_type in ['doc', 'docx']:
            doc = docx.Document(filepath)
            text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
            return text
        
        elif file_type == 'csv':
            text = ""
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                csv_reader = csv.reader(f)
                for row_num, row in enumerate(csv_reader):
                    text += f"Row {row_num + 1}: {', '.join(row)}\n"
            return text
        
        elif file_type == 'json':
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    text = json.dumps(data, indent=2)
                elif isinstance(data, list):
                    text = "\n".join([json.dumps(item, indent=2) for item in data])
                else:
                    text = str(data)
                return text
        
        return ""
    except Exception as e:
        logger.error(f"Error extracting text from {filepath}: {e}")
        return ""

def extract_text_from_image(image_path):
    """Extract text from image using OCR"""
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        logger.error(f"Error extracting text from image: {e}")
        return ""

def convert_pdf_to_images(pdf_path):
    """Convert PDF to list of images"""
    try:
        images = pdf2image.convert_from_path(pdf_path)
        return images
    except Exception as e:
        logger.error(f"Error converting PDF to images: {e}")
        return []

def analyze_image_with_vision(image_path, question="What's in this image?"):
    """Analyze image using Llava vision model"""
    try:
        # Encode image to base64
        with open(image_path, "rb") as img_file:
            img_data = base64.b64encode(img_file.read()).decode('utf-8')
        
        # Prepare prompt for vision model
        prompt = f"{question}\n\nPlease describe what you see in detail."
        
        # Send to Llava model
        payload = {
            "model": "llava:7b-v1.6",  # Vision model
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [img_data]
            }],
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 512
            }
        }
        
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['message']['content']
        else:
            logger.error(f"Vision analysis failed: {response.status_code}")
            return f"Vision analysis failed with status code: {response.status_code}"
            
    except requests.exceptions.ConnectionError:
        return "Cannot connect to vision model. Make sure Ollama is running and Llava model is pulled: 'ollama pull llava'"
    except Exception as e:
        logger.error(f"Error analyzing image with vision: {e}")
        return f"Vision analysis error: {str(e)}"

def process_vision_file(file_id, user_id, filepath, original_filename):
    """Process image/PDF file with vision capabilities"""
    try:
        file_ext = original_filename.split('.')[-1].lower()
        
        # For images
        if file_ext in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp']:
            # Extract text via OCR
            ocr_text = extract_text_from_image(filepath)
            
            # Get vision description
            vision_description = analyze_image_with_vision(filepath)
            
            # Combine results
            combined_text = f"""--- VISION ANALYSIS ---
File: {original_filename}
Type: Image

OCR Text (extracted from image):
{ocr_text if ocr_text else "No text found via OCR"}

AI Visual Description:
{vision_description}

--- END ANALYSIS ---"""
            
            return combined_text
            
        # For PDFs
        elif file_ext == 'pdf':
            images = convert_pdf_to_images(filepath)
            if not images:
                return "Could not process PDF"
            
            # Analyze first page with vision
            temp_image_path = os.path.join(UPLOAD_FOLDER, f"temp_page1_{file_id}.png")
            images[0].save(temp_image_path)
            
            vision_description = analyze_image_with_vision(temp_image_path, 
                f"Describe the first page of this PDF document: {original_filename}")
            
            # Clean up temp file
            try:
                os.remove(temp_image_path)
            except:
                pass
            
            # Extract text traditionally
            pdf_text = extract_text_from_file(filepath, 'pdf')
            
            combined_text = f"""--- PDF ANALYSIS ---
File: {original_filename}
Pages: {len(images)}
Type: PDF with Vision Analysis

Page 1 Vision Analysis:
{vision_description}

PDF Text Content (first 3000 chars):
{pdf_text[:3000] + ("..." if len(pdf_text) > 3000 else "")}

--- END ANALYSIS ---"""
            
            return combined_text
            
        else:
            return "File type not supported for vision analysis"
            
    except Exception as e:
        logger.error(f"Error in vision processing: {e}")
        return f"Vision processing error: {str(e)}"

def chunk_text(text, chunk_size=1000, overlap=200):
    """Split text into overlapping chunks"""
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = start + chunk_size
        if end > text_length:
            end = text_length
        
        chunk = text[start:end]
        
        # Try to end at a sentence boundary
        if end < text_length:
            sentence_enders = '.!?。！？\n'
            for i in range(min(100, len(text) - end)):
                if text[end + i] in sentence_enders:
                    end = end + i + 1
                    chunk = text[start:end]
                    break
        
        chunks.append(chunk.strip())
        start = end - overlap
        
        if start >= text_length:
            break
    
    return [chunk for chunk in chunks if chunk.strip()]

def process_and_store_document(file_id, user_id, filepath, original_filename):
    """Process document and store in ChromaDB"""
    try:
        file_type = original_filename.split('.')[-1].lower()
        
        # Check if it's a vision file (image/PDF)
        is_vision_file = file_type in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp', 'pdf']
        
        if is_vision_file:
            # Process with vision capabilities
            text = process_vision_file(file_id, user_id, filepath, original_filename)
        else:
            # Process normally
            text = extract_text_from_file(filepath, file_type)
        
        if not text or len(text.strip()) < 10:
            logger.warning(f"File {original_filename} has no extractable text")
            return False
        
        # Split text into chunks
        chunks = chunk_text(text)
        
        if not chunks:
            logger.warning(f"No chunks created from {original_filename}")
            return False
        
        # Prepare data for ChromaDB
        chunk_ids = []
        documents = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{file_id}_{i}"
            chunk_ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "user_id": str(user_id),
                "file_id": file_id,
                "filename": original_filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "file_type": file_type,
                "is_vision_file": is_vision_file
            })
        
        # Store in ChromaDB if available
        if chroma_collection:
            chroma_collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=chunk_ids
            )
        else:
            logger.warning("ChromaDB not available, skipping vector storage")
        
        # Update database
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        c.execute('''UPDATE uploaded_files 
                     SET processed = 1, chunk_count = ?
                     WHERE id = ?''', (len(chunks), file_id))
        
        # Store chunks in SQLite for quick retrieval
        for i, chunk in enumerate(chunks):
            c.execute('''INSERT INTO file_chunks 
                         (file_id, chunk_index, chunk_text, embedding_id)
                         VALUES (?, ?, ?, ?)''',
                     (file_id, i, chunk, chunk_ids[i]))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Processed {original_filename}: {len(chunks)} chunks (vision: {is_vision_file})")
        return True
        
    except Exception as e:
        logger.error(f"Error processing document {original_filename}: {e}")
        return False

def search_relevant_documents(query, user_id, n_results=5):
    """Search for relevant documents in ChromaDB"""
    try:
        if not chroma_collection:
            return []
        
        # Query ChromaDB
        results = chroma_collection.query(
            query_texts=[query],
            n_results=n_results,
            where={"user_id": str(user_id)},
            include=["documents", "metadatas", "distances"]
        )
        
        # Format results
        relevant_chunks = []
        if results and results['documents']:
            for i, (doc, metadata, distance) in enumerate(zip(
                results['documents'][0],
                results['metadatas'][0],
                results['distances'][0]
            )):
                relevant_chunks.append({
                    "content": doc,
                    "metadata": metadata,
                    "similarity_score": 1 - distance,
                    "rank": i + 1
                })
        
        return relevant_chunks
    except Exception as e:
        logger.error(f"Error searching documents: {e}")
        return []

def get_user_id(username):
    """Get user ID from username"""
    conn = sqlite3.connect('users.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def create_default_user():
    """Create default demo user if not exists"""
    conn = sqlite3.connect('users.db', check_same_thread=False)
    c = conn.cursor()
    
    # Check if demo user exists with correct password
    c.execute("SELECT username, password_hash FROM users WHERE username = 'demo'")
    user = c.fetchone()
    
    if user:
        # Verify the password hash is correct
        expected_hash = hash_password("demo123")
        if user[1] != expected_hash:
            logger.info("⚠️  Demo user password hash incorrect, resetting...")
            c.execute("DELETE FROM users WHERE username = 'demo'")
        else:
            logger.info("✅ Demo user already exists with correct password")
            conn.close()
            return
    
    # Create demo user with correct password hash
    demo_password = "demo123"
    password_hash = hash_password(demo_password)
    
    c.execute('''INSERT INTO users (username, email, password_hash) 
                 VALUES (?, ?, ?)''',
             ('demo', 'demo@example.com', password_hash))
    
    conn.commit()
    
    # Verify the user was created
    c.execute("SELECT username, password_hash FROM users WHERE username = 'demo'")
    user = c.fetchone()
    if user:
        logger.info(f"✅ Created/Reset default demo user: {user[0]}")
        logger.info(f"   Password hash: {user[1][:30]}...")
    else:
        logger.error("❌ Failed to create demo user")
    
    conn.close()

create_default_user()

# ==================== DEBUG ENDPOINTS ====================

@app.route('/api/chat/test', methods=['POST'])
def test_chat_simple():
    """Simple test chat without authentication"""
    try:
        data = request.get_json()
        message = data.get('message', 'Hello')
        
        logger.info(f"🔍 Test chat with message: {message}")
        
        # Direct Ollama test
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": message}],
            "stream": False
        }
        
        logger.info(f"📤 Sending to Ollama: {payload}")
        
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=30)
        
        logger.info(f"📥 Ollama response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({
                "success": True,
                "response": result['message']['content'],
                "ollama_status": "working"
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Ollama error: {response.status_code}",
                "ollama_status": "not working"
            })
            
    except Exception as e:
        logger.error(f"Test chat error: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "ollama_status": "error"
        })

@app.route('/api/debug/session', methods=['GET'])
def debug_session():
    """Debug session info"""
    return jsonify({
        "session_data": dict(session),
        "user_id_in_session": session.get('user_id'),
        "username_in_session": session.get('username')
    })

# ==================== ROUTES ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    status = {
        "flask": "healthy",
        "database": "healthy",
        "chromadb": "healthy" if chroma_client else "unhealthy",
        "ollama": "unknown",
        "vision": "unknown"
    }
    
    # Check database
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT 1")
        
        # Check if demo user exists
        c.execute("SELECT COUNT(*) FROM users WHERE username = 'demo'")
        demo_count = c.fetchone()[0]
        if demo_count == 0:
            create_default_user()
            status["database"] = "repaired (demo user recreated)"
        else:
            # Verify demo user password
            c.execute("SELECT password_hash FROM users WHERE username = 'demo'")
            demo_hash = c.fetchone()[0]
            expected_hash = hash_password("demo123")
            if demo_hash != expected_hash:
                create_default_user()
                status["database"] = "repaired (password reset)"
        
        conn.close()
    except:
        status["database"] = "unhealthy"
    
    # Check Ollama
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            has_llava = any('llava' in m.get('name', '').lower() for m in models)
            status["ollama"] = "healthy"
            status["vision"] = "available" if has_llava else "llava model not found"
        else:
            status["ollama"] = "unhealthy"
    except:
        status["ollama"] = "unhealthy"
    
    return jsonify({
        "success": True,
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    })

@app.route('/api/login', methods=['POST'])
def login():
    """User login - FIXED VERSION with better debugging"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        logger.info(f"🔐 Login attempt for user: '{username}'")
        
        if not username or not password:
            return jsonify({"success": False, "error": "Username and password required"}), 400
        
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        # Get user from database
        c.execute('''SELECT id, username, password_hash FROM users 
                     WHERE username = ?''', (username,))
        user = c.fetchone()
        
        if user:
            user_id, db_username, stored_hash = user
            logger.info(f"✅ Found user: {db_username}")
            logger.info(f"   Stored hash: {stored_hash[:30]}...")
            
            # Calculate hash for provided password
            provided_hash = hash_password(password)
            logger.info(f"   Provided hash: {provided_hash[:30]}...")
            logger.info(f"   Hashes match: {provided_hash == stored_hash}")
            
            if provided_hash == stored_hash:
                session['user_id'] = user_id
                session['username'] = db_username
                session.permanent = True
                
                # Update last login
                c.execute('''UPDATE users SET last_login = CURRENT_TIMESTAMP 
                             WHERE id = ?''', (user_id,))
                conn.commit()
                conn.close()
                
                logger.info(f"✅ User logged in successfully: {db_username}")
                
                return jsonify({
                    "success": True,
                    "message": "Login successful",
                    "user": {
                        "id": user_id,
                        "username": db_username
                    }
                })
            else:
                logger.warning(f"❌ Password mismatch for user: {username}")
                logger.info(f"   Stored: {stored_hash[:30]}...")
                logger.info(f"   Provided: {provided_hash[:30]}...")
                
                # Offer password reset for demo user
                if username.lower() == "demo":
                    create_default_user()
                    return jsonify({
                        "success": False,
                        "error": "Demo password reset. Try: demo / demo123",
                        "suggestion": "Use username: demo, password: demo123"
                    }), 401
                
                return jsonify({
                    "success": False,
                    "error": "Invalid username or password",
                    "debug": {
                        "user_found": True,
                        "stored_hash_start": stored_hash[:10],
                        "provided_hash_start": provided_hash[:10]
                    }
                }), 401
        else:
            logger.warning(f"❌ User not found: {username}")
            
            # List all users for debugging
            c.execute("SELECT username FROM users")
            all_users = [row[0] for row in c.fetchall()]
            conn.close()
            
            return jsonify({
                "success": False,
                "error": "Invalid username or password",
                "suggestion": f"Try demo user: username: demo, password: demo123",
                "debug": {
                    "available_users": all_users
                }
            }), 401
            
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/signup', methods=['POST'])
def signup():
    """User registration - FIXED with better error handling"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        
        if len(username) < 3:
            return jsonify({"success": False, "error": "Username must be at least 3 characters"}), 400
        
        if len(password) < 6:
            return jsonify({"success": False, "error": "Password must be at least 6 characters"}), 400
        
        if '@' not in email:
            return jsonify({"success": False, "error": "Invalid email address"}), 400
        
        password_hash = hash_password(password)
        logger.info(f"🔐 Signup - Username: {username}, Email: {email}")
        logger.info(f"   Password hash: {password_hash[:30]}...")
        
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        try:
            c.execute('''INSERT INTO users (username, email, password_hash) 
                         VALUES (?, ?, ?)''', 
                     (username, email, password_hash))
            user_id = c.lastrowid
            conn.commit()
            
            session['user_id'] = user_id
            session['username'] = username
            
            logger.info(f"✅ New user registered: {username}")
            
            return jsonify({
                "success": True,
                "message": "Account created successfully",
                "user": {
                    "id": user_id,
                    "username": username,
                    "email": email
                }
            })
            
        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_msg = str(e).lower()
            if "username" in error_msg:
                return jsonify({"success": False, "error": "Username already exists"}), 409
            elif "email" in error_msg:
                return jsonify({"success": False, "error": "Email already registered"}), 409
            else:
                return jsonify({"success": False, "error": "Database integrity error"}), 409
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"Signup error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    """User logout"""
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"})

@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    """Check authentication status"""
    if 'user_id' in session:
        return jsonify({
            "authenticated": True,
            "user": {
                "id": session.get('user_id'),
                "username": session.get('username')
            }
        })
    return jsonify({"authenticated": False})

# ==================== PASSWORD RESET ENDPOINTS ====================

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    """Reset password for a user"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        username = data.get('username', '').strip()
        new_password = data.get('new_password', '').strip()
        
        if not username or not new_password:
            return jsonify({"success": False, "error": "Username and new password required"}), 400
        
        if len(new_password) < 6:
            return jsonify({"success": False, "error": "Password must be at least 6 characters"}), 400
        
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        # Check if user exists
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        
        if not user:
            conn.close()
            return jsonify({"success": False, "error": "User not found"}), 404
        
        # Update password
        password_hash = hash_password(new_password)
        c.execute("UPDATE users SET password_hash = ? WHERE username = ?", 
                 (password_hash, username))
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Password reset for user: {username}")
        
        return jsonify({
            "success": True,
            "message": "Password reset successfully"
        })
        
    except Exception as e:
        logger.error(f"Password reset error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/debug/users', methods=['GET'])
def debug_users():
    """Debug endpoint to see all users and their password hashes"""
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT id, username, email, password_hash, created_at, last_login 
                     FROM users ORDER BY created_at DESC''')
        
        users = []
        for row in c.fetchall():
            users.append({
                "id": row[0],
                "username": row[1],
                "email": row[2],
                "password_hash": row[3],
                "password_hash_start": row[3][:30] + "..." if row[3] else None,
                "created_at": row[4],
                "last_login": row[5],
                "is_demo": row[1] == 'demo'
            })
        
        conn.close()
        
        return jsonify({
            "success": True,
            "users": users,
            "count": len(users),
            "demo_hash_example": hash_password("demo123")[:30] + "..."
        })
        
    except Exception as e:
        logger.error(f"Debug users error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== ADMIN ENDPOINTS ====================

@app.route('/api/admin/reset-demo', methods=['POST'])
def reset_demo_user():
    """Reset demo user to default credentials"""
    try:
        create_default_user()
        return jsonify({
            "success": True,
            "message": "Demo user reset to: demo / demo123"
        })
    except Exception as e:
        logger.error(f"Reset demo error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/admin/users', methods=['GET'])
def list_users():
    """List all users (admin only)"""
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT id, username, email, created_at, last_login 
                     FROM users ORDER BY created_at DESC''')
        
        users = []
        for row in c.fetchall():
            users.append({
                "id": row[0],
                "username": row[1],
                "email": row[2],
                "created_at": row[3],
                "last_login": row[4]
            })
        
        conn.close()
        
        return jsonify({
            "success": True,
            "users": users,
            "count": len(users)
        })
        
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== VISION ENDPOINTS ====================

@app.route('/api/vision/analyze', methods=['POST'])
def vision_analyze():
    """Direct vision analysis of uploaded image"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        # Check for file upload
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "error": "No file selected"}), 400
        
        if not allowed_file(file.filename):
            return jsonify({"success": False, "error": "File type not allowed"}), 400
        
        # Save temp file
        file_id = str(uuid.uuid4())
        temp_filename = f"temp_vision_{file_id}_{file.filename}"
        temp_path = os.path.join(UPLOAD_FOLDER, temp_filename)
        file.save(temp_path)
        
        # Get question
        data = request.form
        question = data.get('question', "What's in this image?")
        
        # Check if it's an image or PDF
        file_ext = file.filename.split('.')[-1].lower()
        is_pdf = file_ext == 'pdf'
        
        if is_pdf:
            # Convert first page of PDF to image
            images = convert_pdf_to_images(temp_path)
            if not images:
                return jsonify({"success": False, "error": "Could not process PDF"}), 400
            
            # Save first page as temp image
            temp_image_path = os.path.join(UPLOAD_FOLDER, f"temp_pdf_page1_{file_id}.png")
            images[0].save(temp_image_path)
            
            # Analyze with vision
            vision_response = analyze_image_with_vision(temp_image_path, 
                f"Describe the first page of this PDF document: {file.filename}")
            
            # Clean up
            try:
                os.remove(temp_image_path)
            except:
                pass
        else:
            # Analyze image directly
            vision_response = analyze_image_with_vision(temp_path, question)
        
        # Also extract OCR text
        ocr_text = ""
        if file_ext in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp']:
            ocr_text = extract_text_from_image(temp_path)
        
        # Clean up temp file
        try:
            os.remove(temp_path)
        except:
            pass
        
        return jsonify({
            "success": True,
            "response": vision_response,
            "ocr_text": ocr_text if ocr_text else None,
            "question": question,
            "filename": file.filename,
            "file_type": "PDF" if is_pdf else "Image"
        })
        
    except Exception as e:
        logger.error(f"Vision analysis error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/vision/models', methods=['GET'])
def get_vision_models():
    """Check if vision models are available"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        if response.status_code == 200:
            models = response.json().get('models', [])
            
            vision_models = []
            for model in models:
                model_name = model.get('name', '')
                if 'llava' in model_name.lower() or 'bakllava' in model_name.lower() or 'vision' in model_name.lower():
                    vision_models.append({
                        "name": model_name,
                        "size": model.get('size', 0),
                        "modified": model.get('modified_at', '')
                    })
            
            return jsonify({
                "success": True,
                "vision_models": vision_models,
                "has_vision": len(vision_models) > 0
            })
        else:
            return jsonify({
                "success": False,
                "error": "Cannot connect to Ollama"
            }), 503
    except Exception as e:
        logger.error(f"Error checking vision models: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== CHAT ENDPOINTS ====================

@app.route('/api/chat/sessions', methods=['GET'])
def get_chat_sessions():
    """Get all chat sessions for current user"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT cs.id, cs.title, cs.created_at, cs.updated_at,
                            COUNT(m.id) as message_count
                     FROM chat_sessions cs
                     LEFT JOIN messages m ON cs.id = m.session_id
                     WHERE cs.user_id = ? AND cs.is_active = 1
                     GROUP BY cs.id
                     ORDER BY cs.updated_at DESC''', 
                 (session['user_id'],))
        
        sessions = []
        for row in c.fetchall():
            sessions.append({
                "id": row[0],
                "title": row[1] or "New Chat",
                "created_at": row[2],
                "updated_at": row[3],
                "message_count": row[4]
            })
        
        conn.close()
        return jsonify({"success": True, "sessions": sessions})
        
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/chat/sessions', methods=['POST'])
def create_chat_session():
    """Create a new chat session"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        data = request.get_json() or {}
        title = data.get('title', 'New Chat')
        
        session_id = str(uuid.uuid4())
        
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''INSERT INTO chat_sessions (id, user_id, title)
                     VALUES (?, ?, ?)''',
                 (session_id, session['user_id'], title))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Created chat session: {session_id}")
        
        return jsonify({
            "success": True,
            "session": {
                "id": session_id,
                "title": title,
                "created_at": datetime.now().isoformat()
            }
        })
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/chat/sessions/<session_id>', methods=['GET'])
def get_chat_session(session_id):
    """Get chat session with messages"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT id, title FROM chat_sessions 
                     WHERE id = ? AND user_id = ?''',
                 (session_id, session['user_id']))
        session_data = c.fetchone()
        
        if not session_data:
            conn.close()
            return jsonify({"success": False, "error": "Session not found"}), 404
        
        c.execute('''SELECT role, content, timestamp
                     FROM messages
                     WHERE session_id = ?
                     ORDER BY timestamp ASC''',
                 (session_id,))
        
        messages = []
        for row in c.fetchall():
            messages.append({
                "role": row[0],
                "content": row[1],
                "timestamp": row[2]
            })
        
        conn.close()
        
        return jsonify({
            "success": True,
            "session": {
                "id": session_data[0],
                "title": session_data[1],
                "messages": messages
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/chat/sessions/<session_id>/messages', methods=['POST'])
def add_message(session_id):
    """Add a message to chat session"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        role = data.get('role', 'user')
        content = data.get('content', '').strip()
        
        if not content:
            return jsonify({"success": False, "error": "Message content required"}), 400
        
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT id FROM chat_sessions 
                     WHERE id = ? AND user_id = ?''',
                 (session_id, session['user_id']))
        if not c.fetchone():
            conn.close()
            return jsonify({"success": False, "error": "Session not found"}), 404
        
        c.execute('''INSERT INTO messages (session_id, role, content)
                     VALUES (?, ?, ?)''',
                 (session_id, role, content))
        
        c.execute('''UPDATE chat_sessions 
                     SET updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''', (session_id,))
        
        conn.commit()
        message_id = c.lastrowid
        conn.close()
        
        return jsonify({
            "success": True,
            "message": {
                "id": message_id,
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat()
            }
        })
        
    except Exception as e:
        logger.error(f"Error adding message: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/chat/sessions/<session_id>', methods=['DELETE'])
def delete_chat_session(session_id):
    """Delete a chat session"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT id FROM chat_sessions 
                     WHERE id = ? AND user_id = ?''',
                 (session_id, session['user_id']))
        if not c.fetchone():
            conn.close()
            return jsonify({"success": False, "error": "Session not found"}), 404
        
        c.execute('''UPDATE chat_sessions 
                     SET is_active = 0
                     WHERE id = ?''', (session_id,))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Deleted chat session: {session_id}")
        
        return jsonify({"success": True, "message": "Session deleted"})
        
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/chat/sessions/<session_id>/title', methods=['PUT'])
def update_session_title(session_id):
    """Update chat session title"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        title = data.get('title', '').strip()
        if not title:
            return jsonify({"success": False, "error": "Title required"}), 400
        
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT id FROM chat_sessions 
                     WHERE id = ? AND user_id = ?''',
                 (session_id, session['user_id']))
        if not c.fetchone():
            conn.close()
            return jsonify({"success": False, "error": "Session not found"}), 404
        
        c.execute('''UPDATE chat_sessions 
                     SET title = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''', (title, session_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "Title updated",
            "title": title
        })
        
    except Exception as e:
        logger.error(f"Error updating title: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== CHAT COMPLETION - ULTIMATE FIX ====================

@app.route('/api/chat/completion', methods=['POST'])
def chat_completion():
    """Main chat completion with RAG - ULTIMATE FIX FOR GREETINGS"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        message = data.get('message', '').strip()
        session_id = data.get('session_id')
        use_context = data.get('use_context', True)
        
        if not message:
            return jsonify({"success": False, "error": "Message required"}), 400
        
        logger.info(f"📨 Received raw message: '{message[:100]}...'")
        
        # ========== 🔥 ULTIMATE FIX: Extract the actual user message ==========
        original_message = message
        
        # Check for common UI text patterns and extract the actual query
        patterns_to_clean = [
            r'Search results for "([^"]+)"',
            r'Search results for\s+(\w+)',
            r'My analysis of "([^"]+)"',
            r'analysis of "([^"]+)" indicates',
            r'results for "([^"]+)" reveal',
            r'for "([^"]+)" reveal'
        ]
        
        cleaned_message = message
        for pattern in patterns_to_clean:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                cleaned_message = match.group(1)
                logger.info(f"🔄 Extracted query from pattern '{pattern}': '{cleaned_message}'")
                break
        
        # If no pattern matched, try to find the first word in quotes
        if cleaned_message == message and '"' in message:
            quoted = re.findall(r'"([^"]+)"', message)
            if quoted:
                cleaned_message = quoted[0]
                logger.info(f"🔄 Extracted quoted text: '{cleaned_message}'")
        
        # If still no match, try to get the first meaningful word
        if cleaned_message == message and len(message.split()) > 3:
            # Get the first word that looks like a query (not "Search", "results", "for", etc.)
            ignore_words = {'search', 'results', 'for', 'my', 'analysis', 'of', 'reveals', 'reveal', 
                           'indicates', 'several', 'patterns', 'anti', 'experts', 'generally'}
            words = message.lower().split()
            for word in words:
                if word not in ignore_words and len(word) > 1:
                    cleaned_message = word
                    logger.info(f"🔄 Extracted first meaningful word: '{cleaned_message}'")
                    break
        
        # Finally, check if it's a greeting
        greetings = ['hi', 'hello', 'hey', 'greetings', 'howdy', 'hi there', 'hello there']
        simple_greeting = cleaned_message.lower() in greetings
        
        # If it's just "hi" but got extracted weirdly
        if len(cleaned_message) <= 2 and any(greet in message.lower() for greet in ['hi', 'hello']):
            for greet in greetings:
                if greet in message.lower():
                    cleaned_message = greet
                    simple_greeting = True
                    break
        
        # For greetings, definitely disable context
        if simple_greeting:
            use_context = False
            logger.info(f"👋 Detected greeting: '{cleaned_message}' - Context disabled")
        
        # Use the cleaned message for processing
        message = cleaned_message
        
        # ========== END CLEANUP ==========
        
        # Verify session ownership if session_id provided
        if session_id:
            conn = sqlite3.connect('users.db', check_same_thread=False)
            c = conn.cursor()
            c.execute('''SELECT id FROM chat_sessions 
                         WHERE id = ? AND user_id = ?''',
                     (session_id, session['user_id']))
            if not c.fetchone():
                conn.close()
                return jsonify({"success": False, "error": "Session not found"}), 404
            conn.close()
        
        # Save user message (use original to preserve what was actually sent)
        if session_id:
            conn = sqlite3.connect('users.db', check_same_thread=False)
            c = conn.cursor()
            c.execute('''INSERT INTO messages (session_id, role, content)
                         VALUES (?, ?, ?)''',
                     (session_id, 'user', original_message))
            conn.commit()
            conn.close()
        
        # Build context from uploaded files if enabled
        context_parts = []
        if use_context and not simple_greeting:  # Skip context for greetings
            relevant_chunks = search_relevant_documents(message, session['user_id'])
            if relevant_chunks:
                context_parts.append("## Relevant Information from Your Documents:\n")
                for i, chunk in enumerate(relevant_chunks[:3]):
                    content = chunk['content'][:500]
                    filename = chunk['metadata'].get('filename', 'Unknown')
                    file_type = chunk['metadata'].get('file_type', '')
                    is_vision = chunk['metadata'].get('is_vision_file', False)
                    
                    source_info = f"'{filename}'"
                    if is_vision:
                        source_info += f" (Vision Analysis of {file_type.upper()})"
                    
                    context_parts.append(f"{i+1}. From {source_info}:\n{content}...\n")
        
        # Prepare messages for Ollama - SIMPLIFIED for greetings
        if simple_greeting:
            # For greetings, use a very simple prompt
            messages = [
                {"role": "system", "content": "You are a friendly AI assistant. Respond naturally to greetings."},
                {"role": "user", "content": message}
            ]
        else:
            # For normal messages, use the full system prompt
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT}
            ]
            
            # Add context if available
            if context_parts:
                context = "\n".join(context_parts)
                messages.append({"role": "system", "content": context})
            
            # Add conversation history if session_id provided
            if session_id:
                try:
                    conn = sqlite3.connect('users.db', check_same_thread=False)
                    c = conn.cursor()
                    c.execute('''SELECT role, content FROM messages
                                 WHERE session_id = ?
                                 ORDER BY timestamp ASC
                                 LIMIT 10''', (session_id,))
                    
                    history_messages = []
                    for row in c.fetchall():
                        history_messages.append({
                            "role": row[0],
                            "content": row[1]
                        })
                    conn.close()
                    
                    # Add history to messages (excluding current message)
                    for msg in history_messages[-6:]:
                        messages.append(msg)
                except Exception as e:
                    logger.warning(f"Could not load chat history: {e}")
            
            # Add current user message
            messages.append({"role": "user", "content": message})
        
        logger.info(f"📤 Preparing {len(messages)} messages for Ollama")
        logger.info(f"💬 Final message to AI: '{message}'")
        
        # Prepare Ollama request
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 512 if simple_greeting else 2048
            }
        }
        
        logger.info(f"📤 Sending to Ollama (model: {OLLAMA_MODEL})")
        
        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json=payload,
                timeout=120
            )
            
            logger.info(f"📥 Ollama response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                ai_response = result['message']['content']
                
                logger.info(f"✅ Got response: {ai_response[:100]}...")
                
                # Save AI response
                if session_id:
                    conn = sqlite3.connect('users.db', check_same_thread=False)
                    c = conn.cursor()
                    c.execute('''INSERT INTO messages (session_id, role, content)
                                 VALUES (?, ?, ?)''',
                             (session_id, 'assistant', ai_response))
                    conn.commit()
                    conn.close()
                
                return jsonify({
                    "success": True,
                    "response": ai_response,
                    "session_id": session_id,
                    "model_used": OLLAMA_MODEL,
                    "original_message": original_message,
                    "cleaned_message": message,
                    "was_greeting": simple_greeting
                })
            else:
                error_msg = f"Ollama error: {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg = f"{error_msg} - {error_detail.get('error', '')}"
                except:
                    pass
                
                logger.error(error_msg)
                return jsonify({
                    "success": False,
                    "error": error_msg
                }), 500
                
        except requests.exceptions.ConnectionError:
            logger.error("❌ Cannot connect to Ollama")
            return jsonify({
                "success": False,
                "error": "Ollama not running. Start it with: ollama serve"
            }), 503
        except requests.exceptions.Timeout:
            logger.error("❌ Ollama request timeout")
            return jsonify({
                "success": False,
                "error": "Request timeout. Try a shorter message."
            }), 504
        except Exception as e:
            logger.error(f"❌ Ollama request error: {e}")
            return jsonify({
                "success": False,
                "error": f"Ollama error: {str(e)}"
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Chat completion error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== DIRECT CHAT ENDPOINT ====================

@app.route('/api/chat/direct', methods=['POST'])
def direct_chat():
    """Direct chat without any processing - for testing"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({"success": False, "error": "Message required"}), 400
        
        logger.info(f"🎯 Direct chat test: '{message}'")
        
        # Super simple direct request
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "user", "content": message}
            ],
            "stream": False
        }
        
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({
                "success": True,
                "response": result['message']['content']
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Ollama error: {response.status_code}"
            }), 500
            
    except Exception as e:
        logger.error(f"Direct chat error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== FILE UPLOAD ENDPOINTS ====================

@app.route('/api/files/upload', methods=['POST'])
def upload_file():
    """Upload and process files"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file part"}), 400
        
        files = request.files.getlist('file')
        if not files or files[0].filename == '':
            return jsonify({"success": False, "error": "No selected files"}), 400
        
        uploaded_files = []
        
        for file in files:
            if not allowed_file(file.filename):
                logger.warning(f"File type not allowed: {file.filename}")
                continue
            
            # Generate unique filename
            file_id = str(uuid.uuid4())
            original_filename = secure_filename(file.filename)
            file_extension = original_filename.rsplit('.', 1)[-1].lower()
            stored_filename = f"{file_id}.{file_extension}"
            filepath = os.path.join(UPLOAD_FOLDER, stored_filename)
            
            # Save file
            file.save(filepath)
            file_size = os.path.getsize(filepath)
            
            # Save to database
            conn = sqlite3.connect('users.db', check_same_thread=False)
            c = conn.cursor()
            c.execute('''INSERT INTO uploaded_files 
                         (id, user_id, original_filename, stored_filename, 
                          file_type, file_size)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                     (file_id, session['user_id'], original_filename, 
                      stored_filename, file_extension, file_size))
            conn.commit()
            conn.close()
            
            # Process in background
            import threading
            thread = threading.Thread(
                target=process_and_store_document,
                args=(file_id, session['user_id'], filepath, original_filename)
            )
            thread.daemon = True
            thread.start()
            
            uploaded_files.append({
                "id": file_id,
                "filename": original_filename,
                "size": file_size,
                "type": file_extension,
                "uploaded_at": datetime.now().isoformat(),
                "is_vision": file_extension in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp', 'pdf']
            })
            
            logger.info(f"✅ Uploaded file: {original_filename} ({file_size} bytes)")
        
        if not uploaded_files:
            return jsonify({"success": False, "error": "No valid files uploaded"}), 400
        
        return jsonify({
            "success": True,
            "message": f"Uploaded {len(uploaded_files)} file(s)",
            "files": uploaded_files
        })
        
    except Exception as e:
        logger.error(f"File upload error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/files', methods=['GET'])
def get_files():
    """Get user's uploaded files"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT id, original_filename, file_type, file_size, 
                            uploaded_at, processed, chunk_count
                     FROM uploaded_files 
                     WHERE user_id = ?
                     ORDER BY uploaded_at DESC''',
                 (session['user_id'],))
        
        files = []
        for row in c.fetchall():
            file_type = row[2]
            is_vision = file_type in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp', 'pdf']
            
            files.append({
                "id": row[0],
                "filename": row[1],
                "type": file_type,
                "size": row[3],
                "uploaded_at": row[4],
                "processed": bool(row[5]),
                "chunk_count": row[6] or 0,
                "status": "Processed" if row[5] else "Processing",
                "is_vision": is_vision,
                "icon": "🖼️" if file_type in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'] else 
                       "📄" if file_type == 'pdf' else 
                       "📝" if file_type == 'txt' else 
                       "📊" if file_type == 'csv' else 
                       "📋" if file_type == 'doc' or file_type == 'docx' else 
                       "📦" if file_type == 'json' else "📎"
            })
        
        conn.close()
        return jsonify({"success": True, "files": files})
        
    except Exception as e:
        logger.error(f"Error getting files: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/files/<file_id>', methods=['GET'])
def get_file(file_id):
    """Get file details"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT id, original_filename, file_type, file_size, 
                            uploaded_at, processed, chunk_count
                     FROM uploaded_files 
                     WHERE id = ? AND user_id = ?''',
                 (file_id, session['user_id']))
        
        file_data = c.fetchone()
        conn.close()
        
        if not file_data:
            return jsonify({"success": False, "error": "File not found"}), 404
        
        file_type = file_data[2]
        is_vision = file_type in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp', 'pdf']
        
        return jsonify({
            "success": True,
            "file": {
                "id": file_data[0],
                "filename": file_data[1],
                "type": file_type,
                "size": file_data[3],
                "uploaded_at": file_data[4],
                "processed": bool(file_data[5]),
                "chunk_count": file_data[6] or 0,
                "is_vision": is_vision
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting file: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/files/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    """Delete uploaded file"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT stored_filename FROM uploaded_files 
                     WHERE id = ? AND user_id = ?''',
                 (file_id, session['user_id']))
        file_data = c.fetchone()
        
        if not file_data:
            conn.close()
            return jsonify({"success": False, "error": "File not found"}), 404
        
        stored_filename = file_data[0]
        
        # Delete from ChromaDB
        try:
            chroma_collection.delete(where={"file_id": file_id})
        except Exception as e:
            logger.warning(f"Error deleting from ChromaDB: {e}")
        
        # Delete from database
        c.execute("DELETE FROM uploaded_files WHERE id = ?", (file_id,))
        c.execute("DELETE FROM file_chunks WHERE file_id = ?", (file_id,))
        
        conn.commit()
        conn.close()
        
        # Delete physical file
        filepath = os.path.join(UPLOAD_FOLDER, stored_filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        
        logger.info(f"✅ Deleted file: {file_id}")
        
        return jsonify({"success": True, "message": "File deleted"})
        
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/files/<file_id>/content', methods=['GET'])
def get_file_content(file_id):
    """Get file content (text only)"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        conn = sqlite3.connect('users.db', check_same_thread=False)
        c = conn.cursor()
        
        c.execute('''SELECT stored_filename, file_type FROM uploaded_files 
                     WHERE id = ? AND user_id = ?''',
                 (file_id, session['user_id']))
        
        file_data = c.fetchone()
        conn.close()
        
        if not file_data:
            return jsonify({"success": False, "error": "File not found"}), 404
        
        stored_filename, file_type = file_data
        filepath = os.path.join(UPLOAD_FOLDER, stored_filename)
        
        if not os.path.exists(filepath):
            return jsonify({"success": False, "error": "File not found on disk"}), 404
        
        # Extract text based on file type
        if file_type in ['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp']:
            text = extract_text_from_image(filepath)
        elif file_type == 'pdf':
            # Try OCR for PDF
            images = convert_pdf_to_images(filepath)
            if images:
                temp_path = os.path.join(UPLOAD_FOLDER, f"temp_preview_{file_id}.png")
                images[0].save(temp_path)
                text = extract_text_from_image(temp_path)
                try:
                    os.remove(temp_path)
                except:
                    pass
            else:
                text = extract_text_from_file(filepath, file_type)
        else:
            text = extract_text_from_file(filepath, file_type)
        
        if not text:
            return jsonify({"success": False, "error": "Could not extract text"}), 400
        
        return jsonify({
            "success": True,
            "content": text[:10000],
            "truncated": len(text) > 10000,
            "file_type": file_type
        })
        
    except Exception as e:
        logger.error(f"Error getting file content: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== OLLAMA MANAGEMENT ====================

@app.route('/api/ollama/models', methods=['GET'])
def get_ollama_models():
    """Get available Ollama models"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            
            formatted_models = []
            for model in models:
                model_name = model.get('name', '')
                is_vision = 'llava' in model_name.lower() or 'bakllava' in model_name.lower()
                
                formatted_models.append({
                    "name": model_name,
                    "size": model.get('size', 0),
                    "modified": model.get('modified_at', ''),
                    "is_vision": is_vision
                })
            
            return jsonify({
                "success": True,
                "models": formatted_models,
                "current_model": OLLAMA_MODEL
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to fetch models: {response.status_code}"
            }), 500
    except requests.exceptions.ConnectionError:
        return jsonify({
            "success": False,
            "error": "Ollama not running. Start it with: ollama serve"
        }), 503
    except Exception as e:
        logger.error(f"Error getting Ollama models: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/ollama/model', methods=['POST'])
def set_ollama_model():
    """Set the Ollama model to use"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        model = data.get('model', '').strip()
        if not model:
            return jsonify({"success": False, "error": "Model name required"}), 400
        
        # Check if model exists
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        if response.status_code == 200:
            models = response.json().get('models', [])
            model_exists = any(m.get('name') == model for m in models)
            
            if not model_exists:
                return jsonify({
                    "success": False,
                    "error": f"Model '{model}' not found."
                }), 404
            
            # Update global model
            global OLLAMA_MODEL
            OLLAMA_MODEL = model
            
            logger.info(f"✅ Set Ollama model to: {model}")
            
            return jsonify({
                "success": True,
                "message": f"Model set to {model}",
                "model": model
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to verify model"
            }), 500
            
    except Exception as e:
        logger.error(f"Error setting Ollama model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/ollama/pull', methods=['POST'])
def pull_ollama_model():
    """Pull a new Ollama model"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        model = data.get('model', '').strip()
        if not model:
            return jsonify({"success": False, "error": "Model name required"}), 400
        
        # Start pulling (async)
        def pull_model():
            try:
                requests.post(
                    f"{OLLAMA_URL}/api/pull", 
                    json={"name": model},
                    timeout=300
                )
            except:
                pass
        
        import threading
        thread = threading.Thread(target=pull_model)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "success": True,
            "message": f"Started pulling model: {model}",
            "note": "This may take several minutes. Check Ollama terminal for progress."
        })
        
    except Exception as e:
        logger.error(f"Error pulling Ollama model: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== STATIC FILES ====================

@app.route('/')
def index():
    """Serve login page at root"""
    try:
        return send_file('login.html')
    except Exception as e:
        logger.error(f"Error serving login.html: {e}")
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>AI Agent - Login</title>
            <style>
                body {{ font-family: Arial, sans-serif; padding: 40px; text-align: center; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                h1 {{ color: #4CAF50; }}
                .card {{ border: 2px solid #4CAF50; border-radius: 10px; padding: 30px; margin: 20px 0; }}
                .btn {{ display: inline-block; margin: 10px; padding: 12px 24px; background: #4CAF50; 
                        color: white; text-decoration: none; border-radius: 5px; }}
                .btn:hover {{ background: #45a049; }}
                .error {{ color: #f44336; background: #ffebee; padding: 10px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>AI Agent Interface</h1>
                <div class="card">
                    <h2>Login Page Not Found</h2>
                    <p>The login.html file is missing from the current directory.</p>
                    <p class="error">Error: {str(e)}</p>
                    <p>Use these test pages instead:</p>
                    <div>
                        <a href="/test_login" class="btn">Test Login</a>
                        <a href="/chat_test" class="btn">Chat Test</a>
                        <a href="/vision_test" class="btn">Vision Test</a>
                        <a href="/api/health" class="btn">Health Check</a>
                    </div>
                    <p style="margin-top: 30px; font-size: 14px; color: #666;">
                        To fix this, create a login.html file in the same folder as this Python script.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

# Explicit routes for HTML files
@app.route('/login.html')
def serve_login_html():
    """Direct route for Login.html"""
    return index()

@app.route('/Login.html')
def serve_Login_html():
    """Route for capital L Login.html"""
    return index()

@app.route('/index.html')
def serve_index_html():
    """Serve index.html"""
    try:
        return send_file('index.html')
    except:
        return index()

@app.route('/signup.html')
def serve_signup_html():
    """Serve signup.html"""
    try:
        return send_file('signup.html')
    except:
        return index()

@app.route('/chat.html')
def serve_chat_html():
    """Serve chat.html"""
    try:
        return send_file('chat.html')
    except:
        return '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Chat Interface</title>
            <style>
                body { font-family: Arial; padding: 20px; }
                h1 { color: #4CAF50; }
                .box { border: 2px solid #4CAF50; padding: 20px; border-radius: 10px; margin: 20px 0; }
                a { display: inline-block; margin: 10px; padding: 10px 20px; background: #4CAF50; 
                    color: white; text-decoration: none; border-radius: 5px; }
                a:hover { background: #45a049; }
            </style>
        </head>
        <body>
            <h1>Chat Interface</h1>
            <div class="box">
                <p>chat.html file not found.</p>
                <p><a href="/chat_test">Use Chat Test Page Instead</a></p>
            </div>
        </body>
        </html>
        '''

@app.route('/test_login')
def test_login_page():
    """Test login page with debug info"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Login - Fixed Version</title>
        <style>
            body { font-family: Arial; padding: 40px; max-width: 600px; margin: 0 auto; }
            .form-group { margin: 20px 0; }
            input { width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 4px; }
            button { padding: 12px 24px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; margin: 5px; }
            button:hover { background: #45a049; }
            .result { margin: 20px 0; padding: 15px; border-radius: 5px; }
            .success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
            .info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
            .debug { background: #f8f9fa; color: #6c757d; border: 1px solid #e9ecef; font-family: monospace; font-size: 12px; }
            h2 { color: #333; }
            .tab { display: inline-block; padding: 10px 20px; cursor: pointer; border: 1px solid #ddd; margin: 0; }
            .tab.active { background: #4CAF50; color: white; }
            .tab-content { display: none; padding: 20px; border: 1px solid #ddd; border-top: none; }
            .tab-content.active { display: block; }
        </style>
    </head>
    <body>
        <h2>Test Login - Fixed Version</h2>
        
        <div>
            <div class="tab active" onclick="switchTab('login')">Login</div>
            <div class="tab" onclick="switchTab('signup')">Signup</div>
            <div class="tab" onclick="switchTab('debug')">Debug</div>
            <div class="tab" onclick="switchTab('reset')">Reset</div>
        </div>
        
        <div id="login-tab" class="tab-content active">
            <div class="info">
                <strong>Demo Credentials:</strong><br>
                Username: demo<br>
                Password: demo123
            </div>
            
            <div class="form-group">
                <label>Username:</label>
                <input type="text" id="username" value="demo">
            </div>
            
            <div class="form-group">
                <label>Password:</label>
                <input type="password" id="password" value="demo123">
            </div>
            
            <button onclick="login()">Login</button>
            <button onclick="testDirectLogin()" style="background: #008CBA;">Test Direct</button>
            
            <div id="login-result"></div>
        </div>
        
        <div id="signup-tab" class="tab-content">
            <div class="form-group">
                <label>Username (min 3 chars):</label>
                <input type="text" id="signup-username" placeholder="Enter username">
            </div>
            
            <div class="form-group">
                <label>Email:</label>
                <input type="email" id="signup-email" placeholder="Enter email">
            </div>
            
            <div class="form-group">
                <label>Password (min 6 chars):</label>
                <input type="password" id="signup-password" placeholder="Enter password">
            </div>
            
            <button onclick="signup()">Create Account</button>
            
            <div id="signup-result"></div>
        </div>
        
        <div id="debug-tab" class="tab-content">
            <button onclick="debugUsers()">Show All Users</button>
            <button onclick="debugSession()">Show Session Info</button>
            <button onclick="debugHealth()">Check Health</button>
            
            <div id="debug-result"></div>
        </div>
        
        <div id="reset-tab" class="tab-content">
            <div class="info">
                <strong>Reset Password</strong><br>
                Use this to reset a user's password if login fails.
            </div>
            
            <div class="form-group">
                <label>Username to reset:</label>
                <input type="text" id="reset-username" placeholder="Enter username">
            </div>
            
            <div class="form-group">
                <label>New Password (min 6 chars):</label>
                <input type="password" id="reset-password" placeholder="Enter new password">
            </div>
            
            <button onclick="resetPassword()" style="background: #ff9800;">Reset Password</button>
            <button onclick="resetDemoUser()" style="background: #9c27b0;">Reset Demo User</button>
            
            <div id="reset-result"></div>
        </div>
        
        <script>
            function switchTab(tabName) {
                // Hide all tabs
                document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
                
                // Show selected tab
                document.getElementById(tabName + '-tab').classList.add('active');
                event.target.classList.add('active');
            }
            
            async function login() {
                const username = document.getElementById('username').value.trim();
                const password = document.getElementById('password').value.trim();
                const resultDiv = document.getElementById('login-result');
                
                if (!username || !password) {
                    resultDiv.innerHTML = '<div class="error">Please enter username and password</div>';
                    return;
                }
                
                resultDiv.innerHTML = '<div class="info">Logging in...</div>';
                
                try {
                    const response = await fetch('/api/login', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({username, password})
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        resultDiv.innerHTML = `
                            <div class="success">
                                <strong>Login successful!</strong><br><br>
                                User: ${data.user.username}<br>
                                ID: ${data.user.id}<br><br>
                                <a href="/chat_test" style="color: #155724; font-weight: bold;">Go to Chat</a>
                            </div>
                        `;
                    } else {
                        resultDiv.innerHTML = `
                            <div class="error">
                                <strong>Login failed:</strong> ${data.error}<br>
                                ${data.suggestion ? '<br>' + data.suggestion : ''}
                                ${data.debug ? '<br><br><strong>Debug Info:</strong><br>' + JSON.stringify(data.debug, null, 2) : ''}
                            </div>
                        `;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
            
            async function testDirectLogin() {
                // Test with direct credentials
                const resultDiv = document.getElementById('login-result');
                resultDiv.innerHTML = '<div class="info">Testing direct login with demo/demo123...</div>';
                
                try {
                    const response = await fetch('/api/login', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({username: 'demo', password: 'demo123'})
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        resultDiv.innerHTML = `<div class="success">Direct demo login successful!</div>`;
                    } else {
                        resultDiv.innerHTML = `<div class="error">Direct demo login failed: ${data.error}</div>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
            
            async function signup() {
                const username = document.getElementById('signup-username').value.trim();
                const email = document.getElementById('signup-email').value.trim();
                const password = document.getElementById('signup-password').value.trim();
                const resultDiv = document.getElementById('signup-result');
                
                if (!username || username.length < 3) {
                    resultDiv.innerHTML = '<div class="error">Username must be at least 3 characters</div>';
                    return;
                }
                
                if (!email || !email.includes('@')) {
                    resultDiv.innerHTML = '<div class="error">Please enter a valid email</div>';
                    return;
                }
                
                if (!password || password.length < 6) {
                    resultDiv.innerHTML = '<div class="error">Password must be at least 6 characters</div>';
                    return;
                }
                
                resultDiv.innerHTML = '<div class="info">Creating account...</div>';
                
                try {
                    const response = await fetch('/api/signup', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({username, email, password})
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        resultDiv.innerHTML = `
                            <div class="success">
                                <strong>Account created successfully!</strong><br><br>
                                User: ${data.user.username}<br>
                                Email: ${data.user.email}<br>
                                ID: ${data.user.id}<br><br>
                                <button onclick="switchTab('login')" style="background: #4CAF50; color: white; padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer;">
                                    Go to Login
                                </button>
                            </div>
                        `;
                    } else {
                        resultDiv.innerHTML = `<div class="error">Signup failed: ${data.error}</div>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
            
            async function debugUsers() {
                const resultDiv = document.getElementById('debug-result');
                resultDiv.innerHTML = '<div class="info">Loading users...</div>';
                
                try {
                    const response = await fetch('/api/debug/users');
                    const data = await response.json();
                    
                    if (data.success) {
                        let html = '<div class="debug"><strong>All Users in Database:</strong><br><br>';
                        
                        data.users.forEach(user => {
                            html += `ID: ${user.id}<br>`;
                            html += `Username: ${user.username}<br>`;
                            html += `Email: ${user.email}<br>`;
                            html += `Password Hash: ${user.password_hash_start || user.password_hash}<br>`;
                            html += `Created: ${user.created_at}<br>`;
                            html += `Last Login: ${user.last_login || 'Never'}<br>`;
                            html += `Is Demo: ${user.is_demo ? 'Yes' : 'No'}<br>`;
                            html += '<hr>';
                        });
                        
                        html += `<br><strong>Demo hash example:</strong> ${data.demo_hash_example}<br>`;
                        html += `<strong>Total users:</strong> ${data.count}</div>`;
                        
                        resultDiv.innerHTML = html;
                    } else {
                        resultDiv.innerHTML = `<div class="error">Error: ${data.error}</div>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
            
            async function debugSession() {
                const resultDiv = document.getElementById('debug-result');
                resultDiv.innerHTML = '<div class="info">Checking session...</div>';
                
                try {
                    const response = await fetch('/api/debug/session');
                    const data = await response.json();
                    
                    resultDiv.innerHTML = `<div class="debug">${JSON.stringify(data, null, 2)}</div>`;
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
            
            async function debugHealth() {
                const resultDiv = document.getElementById('debug-result');
                resultDiv.innerHTML = '<div class="info">Checking health...</div>';
                
                try {
                    const response = await fetch('/api/health');
                    const data = await response.json();
                    
                    resultDiv.innerHTML = `<div class="debug">${JSON.stringify(data, null, 2)}</div>`;
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
            
            async function resetPassword() {
                const username = document.getElementById('reset-username').value.trim();
                const password = document.getElementById('reset-password').value.trim();
                const resultDiv = document.getElementById('reset-result');
                
                if (!username || !password || password.length < 6) {
                    resultDiv.innerHTML = '<div class="error">Username and password (min 6 chars) required</div>';
                    return;
                }
                
                resultDiv.innerHTML = '<div class="info">Resetting password...</div>';
                
                try {
                    const response = await fetch('/api/reset-password', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({username, new_password: password})
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        resultDiv.innerHTML = `<div class="success">Password reset successfully for ${username}</div>`;
                    } else {
                        resultDiv.innerHTML = `<div class="error">Reset failed: ${data.error}</div>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
            
            async function resetDemoUser() {
                const resultDiv = document.getElementById('reset-result');
                resultDiv.innerHTML = '<div class="info">Resetting demo user...</div>';
                
                try {
                    const response = await fetch('/api/admin/reset-demo', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'}
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        resultDiv.innerHTML = `<div class="success">${data.message}</div>`;
                    } else {
                        resultDiv.innerHTML = `<div class="error">Reset failed: ${data.error}</div>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
                }
            }
            
            // Auto-login with demo credentials on page load
            window.onload = function() {
                console.log("Test login page loaded");
                setTimeout(() => {
                    document.getElementById('username').value = 'demo';
                    document.getElementById('password').value = 'demo123';
                    // Auto-login commented out for manual testing
                    // login();
                }, 500);
            };
        </script>
    </body>
    </html>
    '''

@app.route('/chat_test')
def chat_test():
    """Simple chat test page"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Chat Test</title>
        <style>
            body { font-family: Arial; padding: 20px; max-width: 800px; margin: 0 auto; }
            #chat { border: 1px solid #ccc; padding: 10px; height: 400px; overflow-y: scroll; margin-bottom: 10px; }
            input { width: 70%; padding: 10px; font-size: 16px; }
            button { padding: 10px 20px; font-size: 16px; background: #4CAF50; color: white; border: none; cursor: pointer; }
            button:hover { background: #45a049; }
            .user { color: blue; margin: 5px 0; }
            .ai { color: green; margin: 5px 0; }
            .error { color: red; margin: 5px 0; }
            .system { color: gray; margin: 5px 0; }
        </style>
    </head>
    <body>
        <h2>Chat Test Page</h2>
        <div id="chat"></div>
        <div>
            <input type="text" id="message" placeholder="Type your message..." onkeypress="handleKeyPress(event)">
            <button onclick="sendMessage()">Send</button>
        </div>
        
        <script>
            function addMessage(role, content) {
                const chat = document.getElementById('chat');
                const div = document.createElement('div');
                div.className = role;
                div.innerHTML = `<strong>${role}:</strong> ${content}`;
                chat.appendChild(div);
                chat.scrollTop = chat.scrollHeight;
            }
            
            function handleKeyPress(e) {
                if (e.key === 'Enter') sendMessage();
            }
            
            async function sendMessage() {
                const input = document.getElementById('message');
                const message = input.value.trim();
                if (!message) return;
                
                addMessage('user', message);
                input.value = '';
                
                try {
                    addMessage('system', 'Sending to server...');
                    
                    const response = await fetch('/api/chat/completion', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            message: message,
                            session_id: 'test-session-123',
                            use_context: false
                        })
                    });
                    
                    const data = await response.json();
                    if (data.success) {
                        addMessage('ai', data.response);
                    } else {
                        addMessage('error', 'Error: ' + (data.error || 'Unknown error'));
                    }
                } catch (error) {
                    addMessage('error', 'Network error: ' + error.message);
                }
            }
            
            // Test Ollama connection
            async function testOllama() {
                try {
                    const response = await fetch('/api/ollama/models');
                    const data = await response.json();
                    if (data.success) {
                        addMessage('system', 'Ollama is running. Models: ' + data.models.map(m => m.name).join(', '));
                    } else {
                        addMessage('error', 'Ollama not running: ' + data.error);
                    }
                } catch (error) {
                    addMessage('error', 'Cannot test Ollama: ' + error.message);
                }
            }
            
            // Auto-test on page load
            window.onload = function() {
                addMessage('system', 'Chat test page loaded. Type a message and press Send.');
                testOllama();
            };
        </script>
    </body>
    </html>
    '''

@app.route('/vision_test')
def vision_test():
    """Serve vision test page"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vision Upload Test</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; }
            h1 { color: #333; }
            .form-group { margin: 20px 0; }
            textarea, input[type="file"] { width: 100%; padding: 10px; margin: 5px 0; }
            button { background: #4CAF50; color: white; padding: 10px 20px; border: none; cursor: pointer; }
            button:hover { background: #45a049; }
            #result { margin-top: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
            .success { background: #d4edda; color: #155724; border-color: #c3e6cb; }
            .error { background: #f8d7da; color: #721c24; border-color: #f5c6cb; }
        </style>
    </head>
    <body>
        <h1>AI Vision Analysis Test</h1>
        
        <form id="visionForm">
            <div class="form-group">
                <label>Upload Image or PDF:</label>
                <input type="file" id="imageFile" accept=".png,.jpg,.jpeg,.bmp,.gif,.webp,.pdf" required>
            </div>
            
            <div class="form-group">
                <label>Question about the file:</label>
                <textarea id="question" rows="3" placeholder="What's in this image?">What's in this image? Describe it in detail.</textarea>
            </div>
            
            <button type="submit">Analyze with AI Vision</button>
        </form>
        
        <div id="result"></div>
        
        <script>
            document.getElementById('visionForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                const fileInput = document.getElementById('imageFile');
                const question = document.getElementById('question').value;
                const resultDiv = document.getElementById('result');
                
                if (!fileInput.files[0]) {
                    resultDiv.innerHTML = '<div class="error">Please select a file</div>';
                    return;
                }
                
                const formData = new FormData();
                formData.append('file', fileInput.files[0]);
                formData.append('question', question);
                
                resultDiv.innerHTML = '<div>Analyzing with vision AI...</div>';
                
                try {
                    const response = await fetch('/api/vision/analyze', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        let html = `<div class="success">
                            <h3>Analysis Complete</h3>
                            <p><strong>File:</strong> ${data.filename} (${data.file_type})</p>
                            <p><strong>Question:</strong> ${data.question}</p>
                            <h4>AI Vision Analysis:</h4>
                            <div style="white-space: pre-wrap; background: white; padding: 10px; border-radius: 3px;">
                                ${data.response}
                            </div>`;
                        
                        if (data.ocr_text) {
                            html += `<h4>OCR Text (Extracted from image):</h4>
                            <div style="white-space: pre-wrap; background: #f0f0f0; padding: 10px; border-radius: 3px;">
                                ${data.ocr_text}
                            </div>`;
                        }
                        
                        html += `</div>`;
                        resultDiv.innerHTML = html;
                    } else {
                        resultDiv.innerHTML = `<div class="error">Error: ${data.error}</div>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<div class="error">Request failed: ${error}</div>`;
                }
            });
        </script>
    </body>
    </html>
    '''

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files with better HTML handling"""
    try:
        # First, check if the file exists as-is
        if os.path.exists(filename):
            return send_file(filename)
        
        # Check for .html extension
        if '.' not in filename:
            # If no extension, try adding .html
            html_file = f"{filename}.html"
            if os.path.exists(html_file):
                return send_file(html_file)
        
        # Try common HTML file patterns
        html_variations = [
            filename,
            f"{filename}.html",
            f"{filename}.HTML",
            filename.lower(),
            f"{filename.lower()}.html"
        ]
        
        for variation in html_variations:
            if os.path.exists(variation):
                return send_file(variation)
        
        # Special case for login
        if filename.lower() in ['login', 'signin', 'sign-in']:
            try:
                return send_file('login.html')
            except:
                pass
        
        # If nothing found, return 404
        return jsonify({
            "success": False, 
            "error": f"File not found: {filename}",
            "tip": "Try accessing / or /chat_test"
        }), 404
        
    except Exception as e:
        logger.error(f"Error serving {filename}: {e}")
        return jsonify({"success": False, "error": f"Internal server error: {str(e)}"}), 500

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({"success": False, "error": "Internal server error"}), 500

@app.errorhandler(413)
def request_too_large(error):
    return jsonify({"success": False, "error": "File too large. Maximum size is 50MB"}), 413

# ==================== MAIN ====================

if __name__ == '__main__':
    print("=" * 70)
    print("LOCAL AI AGENT - COMPLETE FIXED VERSION")
    print("=" * 70)
    print("Features:")
    print("   • FIXED login system with consistent password hashing")
    print("   • Enhanced debugging tools for user management")
    print("   • Password reset functionality")
    print("   • Smart message cleaning for greetings")
    print("   • Complete user management system")
    print("\nAccess Points:")
    print("   • GET  /               - Login page")
    print("   • GET  /test_login     - Test login page with debug tools")
    print("   • GET  /chat_test      - Chat test page")
    print("   • GET  /vision_test    - Vision test page")
    print("\nDemo Credentials:")
    print("   • Username: demo")
    print("   • Password: demo123")
    print("\nDebug Endpoints:")
    print("   • GET  /api/debug/users     - List all users with hashes")
    print("   • POST /api/reset-password  - Reset any user's password")
    print("   • POST /api/admin/reset-demo - Reset demo user")
    print("\nStarting server at: http://127.0.0.1:8080")
    print("=" * 70)
    
    # Check dependencies
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        print("Tesseract OCR is available")
    except:
        print("Tesseract OCR not found. OCR for images may not work.")
    
    # Check if Ollama is running
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            print("Ollama is running")
            print(f"Models: {[m['name'] for m in models]}")
        else:
            print("Ollama not responding properly")
    except:
        print("Ollama not running. Start it with: ollama serve")
        print("The app will start but chat won't work without Ollama.")
    
    # Create startup batch file WITHOUT emojis
    startup_bat = '''@echo off
echo ============================================
echo Starting Local AI Agent - Fixed Login Version
echo ============================================
echo.
echo Access: http://127.0.0.1:8080
echo Test Login: http://127.0.0.1:8080/test_login
echo Login with: demo / demo123
echo.
echo Starting server...
python app.py
'''
    
    try:
        with open('start_ai_agent.bat', 'w', encoding='utf-8') as f:
            f.write(startup_bat)
        print(f"Created startup script: start_ai_agent.bat")
    except:
        print("Could not create startup script (unicode issue)")
    
    print("=" * 70)
    
    # Run on specific IP address
    app.run(host='127.0.0.1', port=8080, debug=True, threaded=True)