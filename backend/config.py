import os

# Path to your local LLM binary file inside the models folder
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")

# Change this filename to the actual model file you download into /models
MODEL_FILENAME = "gpt4all-falcon-q4_0.bin"

# Model configuration (safe defaults for CPU-only machines)
MODEL_SETTINGS = {
    "n_threads": max(1, os.cpu_count() or 4),  # number of CPU threads
    "temp": 0.7,                                # creativity
    "top_p": 0.9,                               # nucleus sampling
    "top_k": 40,                                # token sampling
    "repeat_penalty": 1.1,                      # discourages repetition
    "n_predict": 512,                           # max tokens to generate
    "streaming": False,                         # disable server-side streaming
}

# Server settings
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000

# Basic system prompt to guide the assistant
SYSTEM_PROMPT = (
    "You are a helpful, concise, and friendly offline AI assistant. "
    "Answer clearly and avoid hallucinations. If unsure, say you don't know."
)
