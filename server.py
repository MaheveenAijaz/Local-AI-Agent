from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os
import hashlib

from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama

UPLOAD_FOLDER = "uploads"
VECTOR_DB = "chroma_db"

# Create folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VECTOR_DB, exist_ok=True)

# Tell Flask to use frontend folder
app = Flask(
    __name__,
    template_folder="frontend",
    static_folder="frontend"
)

CORS(app)

# -----------------------
# FRONTEND ROUTES
# -----------------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login")
def login_page():
    return render_template("login.html")

@app.route("/signup")
def signup_page():
    return render_template("signup.html")

@app.route("/chatpage")
def chat_page():
    return render_template("chat.html")

# -----------------------
# DATABASE
# -----------------------

def get_db():
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()

# -----------------------
# SIGNUP API
# -----------------------

@app.route("/api/signup", methods=["POST"])
def signup():

    data = request.json

    username = data["username"]
    password = hash_password(data["password"])

    conn = get_db()

    try:
        conn.execute(
            "INSERT INTO users (username,password) VALUES (?,?)",
            (username, password)
        )

        conn.commit()
        conn.close()

        return jsonify({"status": "success"})

    except:
        conn.close()
        return jsonify({"status": "user_exists"})


# -----------------------
# LOGIN API
# -----------------------

@app.route("/api/login", methods=["POST"])
def login():

    data = request.json

    username = data["username"]
    password = hash_password(data["password"])

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (username, password)
    ).fetchone()

    conn.close()

    if user:
        return jsonify({"success": True})

    return jsonify({"success": False})


# -----------------------
# FILE UPLOAD
# -----------------------

@app.route("/api/upload", methods=["POST"])
def upload_file():

    if "file" not in request.files:
        return jsonify({"error": "No file"})

    file = request.files["file"]

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)

    file.save(filepath)

    process_documents()

    return jsonify({"status": "uploaded"})


# -----------------------
# DOCUMENT PROCESSING
# -----------------------

def process_documents():

    docs = []

    for file in os.listdir(UPLOAD_FOLDER):

        path = os.path.join(UPLOAD_FOLDER, file)

        if file.endswith(".txt"):
            loader = TextLoader(path)
            docs.extend(loader.load())

        if file.endswith(".pdf"):
            loader = PyPDFLoader(path)
            docs.extend(loader.load())

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50
    )

    chunks = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2"
    )

    vectordb = Chroma.from_documents(
        chunks,
        embeddings,
        persist_directory=VECTOR_DB
    )

    vectordb.persist()


# -----------------------
# AI CHAT
# -----------------------

@app.route("/api/chat", methods=["POST"])
def chat():

    question = request.json["message"]

    embeddings = HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2"
    )

    vectordb = Chroma(
        persist_directory=VECTOR_DB,
        embedding_function=embeddings
    )

    docs = vectordb.similarity_search(question, k=3)

    context = "\n".join([doc.page_content for doc in docs])

    prompt = f"""
You are an intelligent AI assistant like ChatGPT.
Answer clearly and helpfully.

Context:
{context}

User Question:
{question}

Answer:
"""

    llm = Ollama(model="llama3")

    response = llm.invoke(prompt)

    return jsonify({"response": response})


# -----------------------
# RUN SERVER
# -----------------------

if __name__ == "__main__":

    print("Local AI Agent Running...")

    app.run(host="127.0.0.1", port=5000, debug=True)