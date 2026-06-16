# Offline AI-Powered Conversational Assistant

A fully offline ChatGPT-style assistant using a local LLM with a Flask backend and a simple web frontend.

## Features
- Local LLM inference via GPT4All
- Privacy-first: no internet needed once the model is downloaded
- Simple, clean web UI
- Chat history maintained client-side
- Health check endpoint

## Prerequisites
- Python 3.10+ recommended (3.8+ should work)
- A CPU-only machine is fine
- A GPT4All model `.bin` file placed in `./models`

## Model download
1. Visit https://gpt4all.io/models to download an offline model. Good CPU-friendly options:
   - `gpt4all-falcon-q4_0.bin`
   - `ggml-gpt4all-j-v1.3-groovy.bin`
   - `ggml-vicuna-7b-1.1-q4_2.bin`

2. Place the downloaded `.bin` file in `./models/`.

3. Update `backend/config.py` and set `MODEL_FILENAME` to the exact filename you downloaded.

## Install backend
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
