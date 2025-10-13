#----------------------
# myOfflineAi-VoiceAssistant
# Creator: vbookshelf
# GitHub: https://github.com/vbookshelf/myOfflineAi-VoiceAssistant
# License: MIT
# Version: 1.0
#----------------------


import base64
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

import fitz  # PyMuPDF
import ollama
import requests
import soundfile as sf
import whisper
from flask import Flask, jsonify, render_template_string, request, Response
from kokoro_onnx import Kokoro
from PIL import Image
from urllib.parse import urlparse



# --- Configuration ---

# Ollama model
DEFAULT_OLLAMA_MODEL = "gemma3:4b"

# LLM Parameters
DEFAULT_NUM_CTX = 16000
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_K = 60
DEFAULT_TOP_P = 0.95
DEFAULT_FREQUENCY_PENALTY = 1.0
DEFAULT_REPEAT_PENALTY = 1.0

DEFAULT_SYSTEM_MESSAGE = "You are emulating Samantha from the movie 'Her.' Your responses are being converted into audio by a TTS system.  Focus on creating responses that sound great when read aloud. Keep your sentences clear and prioritize natural-sounding language.  Do not use emojis. Do not use markdown symbols: #, *. The user has the option to either type in messages or to use voice input. When using voice input an STT system converts the user's voice into text. There may be errors in the voice to text conversion. When that happens the messages you receive may not make sense."

# Store user settings
SETTINGS_FILE = "user_settings.json"

# File to store conversation histories.
# The system message and other parameters associated
# with the chat are also stored. They are auto
# loaded when the chat is loaded.
CONVERSATIONS_FILE = "voice_assistant_history.json"

# PDF & Image Settings
MAX_PAGES = 15
PDF_IMAGE_RES = 1.5 # 150 dpi
MAX_UPLOAD_FILE_SIZE = 20 * 1024 * 1024 # (20MB)

# STT Model
WHISPER_MODEL = "base" # base, turbo, tiny.en



# --- Initialization ---

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_FILE_SIZE


# -----------------------------------------
# PRIVACY FEATURE: Make sure that the app only connects to localhost.
# -----------------------------------------
current_ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
print(f"Current Ollama host: {current_ollama_host!r}")

def is_localhost_url(url):
    if not url: return True
    parsed = urlparse(url if "://" in url else "http://" + url)
    hostname = parsed.hostname
    port = parsed.port or 11434
    if hostname in ("127.0.0.1", "localhost") and port == 11434:
        return True
    return False

if not is_localhost_url(current_ollama_host):
    print(f"[SECURITY] OLLAMA_HOST is not localhost: {current_ollama_host}. Aborting start.", file=sys.stderr)
    sys.exit(1)


# Check for Kokoro model files
KOKORO_ONNX_FILE = "kokoro-v1.0.onnx"
KOKORO_VOICES_FILE = "voices-v1.0.bin"

if not os.path.exists(KOKORO_ONNX_FILE) or not os.path.exists(KOKORO_VOICES_FILE):
    print(f"[ERROR] Kokoro model files not found. Please download them.", file=sys.stderr)
    sys.exit(1)

try:
    print("[INFO] Loading Kokoro text-to-speech engine...")
    kokoro = Kokoro(KOKORO_ONNX_FILE, KOKORO_VOICES_FILE)
    print("[INFO] Kokoro engine loaded successfully.")
except Exception as e:
    print(f"[ERROR] Failed to load Kokoro engine: {e}", file=sys.stderr)
    sys.exit(1)
    
try:
    print(f"[INFO] Loading Whisper STT model ({WHISPER_MODEL}...")
    whisper_model = whisper.load_model(WHISPER_MODEL) #base
    print("[INFO] Whisper model loaded successfully.")
except Exception as e:
    print(f"[ERROR] Failed to load Whisper model: {e}", file=sys.stderr)
    sys.exit(1)
	
	
    
# --- Model & Settings Functions ---

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f: json.dump(settings, f, indent=4)
    except IOError as e:
        print(f"[ERROR] Could not save settings: {e}", file=sys.stderr)

def load_settings():
    defaults = {
        "model": DEFAULT_OLLAMA_MODEL,
        "tts_lang": "en-us", 
        "tts_voice": "af_heart", 
        "tts_speed": 1.0,
        "system_message": DEFAULT_SYSTEM_MESSAGE,
        "temperature": DEFAULT_TEMPERATURE,
        "top_k": DEFAULT_TOP_K,
        "top_p": DEFAULT_TOP_P,
        "frequency_penalty": DEFAULT_FREQUENCY_PENALTY,
        "repeat_penalty": DEFAULT_REPEAT_PENALTY ,
        "num_ctx": DEFAULT_NUM_CTX,
        "tts_enabled": "On"
    }
    if not os.path.exists(SETTINGS_FILE): return defaults
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            # Ensure all keys from defaults are present in the loaded settings
            for key, value in defaults.items():
                settings.setdefault(key, value)
            return settings
    except (IOError, json.JSONDecodeError) as e:
        print(f"[ERROR] Could not read settings file, using defaults: {e}", file=sys.stderr)
        return defaults

def get_ollama_models():
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        resp.raise_for_status()
        return sorted([m["name"] for m in resp.json().get("models", [])])
    except Exception:
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
            lines = result.stdout.strip().splitlines()
            return sorted([line.split()[0] for line in lines[1:]]) if len(lines) > 1 else []
        except Exception:
            return []

# --- History Functions ---
def load_conversations():
    if not os.path.exists(CONVERSATIONS_FILE):
        return []
    try:
        with open(CONVERSATIONS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_conversations(conversations):
    with open(CONVERSATIONS_FILE, "w") as f:
        json.dump(conversations, f, indent=2)
			
			

# --- Garbled Text Filtering Functions ---

def has_repeated_phrases(text: str) -> bool:
    """Checks for garbled, highly repetitive text using regex."""
    pattern = r"(.{5,})(\s*\1){2,}"
    if re.search(pattern, text):
        return True
    return False
	

def contains_mixed_scripts(text: str) -> bool:
    """
    Checks if the text contains characters from multiple distinct scripts,
    which is a strong indicator of a garbled transcription.
    """
    scripts = {
        "latin": re.compile(r'[a-zA-Z]'),
        "arabic": re.compile(r'[\u0600-\u06FF]'),
        "cyrillic": re.compile(r'[\u0400-\u04FF]'),
        "devanagari": re.compile(r'[\u0900-\u097F]'), # Used for Hindi, etc.
        "cjk": re.compile(r'[\u4e00-\u9fff]') # Chinese, Japanese, Korean
    }
    scripts_found = 0
    for script_name in scripts:
        if scripts[script_name].search(text):
            scripts_found += 1
    return scripts_found > 1
	
	
# --- Function to clean the LLM response---

def clean_text(text):
    """
    Removes markdown symbols and emojis from a given string.

    Args:
        text: The input string to clean.

    Returns:
        The cleaned string with markdown and emojis removed.
    """
    # Remove markdown characters: *, #, _, ~, `, >, [, ], (, )
    # This pattern is designed to be simple and remove common formatting.
    markdown_pattern = r'([*_~`#\[\]()<>])'
    text = re.sub(markdown_pattern, '', text)

    # Regex to remove a wide range of emojis and symbols
    # This covers most common emojis, pictographs, symbols, and dingbats.
    try:
        # Wide UCS-4 build (most modern Python installations)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags (iOS)
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE
        )
    except re.error:
        # Narrow UCS-2 build
        emoji_pattern = re.compile(
            u'('
            u'\ud83c[\udf00-\udfff]|'
            u'\ud83d[\udc00-\ude4f\ude80-\udeff]|'
            u'[\u2600-\u26FF\u2700-\u27BF])+',
            flags=re.UNICODE
        )

    text = emoji_pattern.sub(r'', text)

    return text.strip()
	
	
	
def process_chat_and_get_audio(history, model, tts_voice, tts_speed, tts_lang, system_message, llm_options, tts_enabled):
    messages = [{"role": "system", "content": system_message}]
    for msg in history:
        ollama_msg = {"role": msg["role"], "content": msg.get("content", "")}
        if msg.get("images"):
            ollama_msg["images"] = [img.split(',', 1)[1] for img in msg["images"]]
        messages.append(ollama_msg)

    #print(f"\n[INFO] Sending request to model '{model}' with {len(messages)} messages.")
    
    # --- Ollama Inference Timing ---
    start_inference_time = time.time()
    
    # Get num_ctx from options, with a fallback to the default
    num_ctx = int(llm_options.get("num_ctx", DEFAULT_NUM_CTX))
    
    # Combine static options with user-defined ones
    options = {
        "num_ctx": num_ctx,
        "temperature": float(llm_options.get("temperature", 1.0)),
        "top_k": int(llm_options.get("top_k", 60)),
        "top_p": float(llm_options.get("top_p", 0.95)),
        "frequency_penalty": float(llm_options.get("frequency_penalty", 1.0)),
        "repeat_penalty": float(llm_options.get("repeat_penalty", 1.0)),
    }
	
    try:
        response = ollama.chat(
           model=model, 
           messages=messages, 
           options=options
        )
    except ollama.RequestError as e:
        print(f"[ERROR] Ollama request failed: {e}", file=sys.stderr)
        raise ConnectionError("Could not connect to Ollama. Please ensure it is running and accessible.")
	
    inference_duration = time.time() - start_inference_time
    # --- End Timing ---
    
    ai_text_response = response["message"]["content"]
	
    # Clean the response - remove markdown symbols and emojis
    ai_text_response = clean_text(ai_text_response)
	
    #print(f"[INFO] AI response: {ai_text_response}")

    warning_msg = None
    if response.get("done"):
        prompt_tokens, completion_tokens = response.get("prompt_eval_count", 0), response.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens
        print("")
        print("[INFO] Finished processing response.")
        print(f"   [STATS] Prompt Tokens:     {prompt_tokens}\n   [STATS] Completion Tokens: {completion_tokens}\n   [STATS] Total Tokens:      {total_tokens}")
        if total_tokens >= (num_ctx * 0.9):
            warning_msg = f"Chat history is now {total_tokens} tokens (Max: {num_ctx}). The AI may start to lose track of the conversation."
            print(f"[WARNING] {warning_msg}")

    audio_base64 = None
    tts_duration = 0
    if tts_enabled == "On":
        # Map frontend language codes to what the espeak backend expects
        lang_map = {
            "zh": "cmn",   # Kokoro's espeak backend expects 'cmn' for Chinese
            "fr": "fr-fr"  # And 'fr-fr' for French
        }
        kokoro_lang = lang_map.get(tts_lang, tts_lang)

        #print(f"[INFO] Generating audio with voice '{tts_voice}' ({tts_lang} -> {kokoro_lang}) at speed {tts_speed}x.")
        
        # --- Kokoro TTS Timing ---
        start_tts_time = time.time()
        samples, sample_rate = kokoro.create(text=ai_text_response, voice=tts_voice, speed=float(tts_speed), lang=kokoro_lang)
        tts_duration = time.time() - start_tts_time
        # --- End Timing ---

        buffer = io.BytesIO()
        sf.write(buffer, samples, sample_rate, format="WAV")
        buffer.seek(0)
        audio_base64 = base64.b64encode(buffer.read()).decode("utf-8")
    
    return ai_text_response, audio_base64, warning_msg, inference_duration, tts_duration
	

model_list = get_ollama_models()

if not model_list:
    print(f"[WARNING] No Ollama models found. Defaulting to: {DEFAULT_OLLAMA_MODEL}", file=sys.stderr)
    model_list.append(DEFAULT_OLLAMA_MODEL)

# Load settings to determine the initial model
user_settings = load_settings()
saved_model = user_settings.get("model")

if saved_model and saved_model in model_list:
    OLLAMA_MODEL = saved_model
    print(f"[INFO] Loaded last used model from settings: {OLLAMA_MODEL}")
else:
    OLLAMA_MODEL = model_list[0]
    print(f"[INFO] Defaulting to first available model: {OLLAMA_MODEL}")
    # Update settings with the valid default model
    user_settings["model"] = OLLAMA_MODEL
    save_settings(user_settings)
#print(f"[INFO] Loaded initial settings: {user_settings}")


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voice Assistant</title>
	
	<link rel="shortcut icon" type="image/png" href="{{ url_for('static', filename='icon.png') }}">
	
    <style>
        :root {
            --slate-50: #f8fafc;
            --slate-100: #f1f5f9;
            --slate-200: #e2e8f0;
            --slate-300: #cbd5e1;
            --slate-400: #94a3b8;
            --slate-500: #64748b;
            --slate-600: #475569;
            --slate-700: #334155;
            --slate-800: #1e293b;
            --slate-900: #0f172a;
            --indigo-500: #6366f1;
            --indigo-600: #4f46e5;
            --indigo-700: #4338ca;
            --red-500: #ef4444;
            --red-600: #dc2626;
            --chat-shadow-color: rgba(0, 0, 0, 0.1);
        }

        body {
            font-family: Arial, sans-serif;
            background-color: var(--slate-100);
            color: var(--slate-800);
            margin: 0;
            height: 100vh;
            overflow: hidden;
        }

        .app-container {
            display: flex;
            height: 100vh;
        }

        .main-content {
            flex-grow: 1;
            padding: 2rem;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: auto;
        }

        .sidebar {
            width: 320px;
            background-color: var(--slate-800);
            color: var(--slate-200);
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            border-right: 1px solid var(--slate-700);
            transition: transform 0.3s ease-in-out;
            flex-shrink: 0;
            z-index: 100;
            overflow-y: auto;
        }

        .chat-view {
            width: 100%;
            max-width: 900px;
            height: 90vh;
            max-height: 850px;
            display: flex;
            flex-direction: column;
            background-color: white;
            border-radius: 1rem;
            overflow: hidden;
            box-shadow: 0 10px 25px -5px var(--chat-shadow-color), 0 4px 6px -2px var(--chat-shadow-color);
            position: relative;
            transition: box-shadow 0.3s ease-in-out;
        }

        .chat-view.mic-active-shadow {
            --chat-shadow-color: rgba(79, 70, 229, 0.9);
        }

        .sidebar-section {
            margin-bottom: 1.5rem;
        }

        .sidebar-section label,
        .collapsible-header {
            display: block;
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--slate-300);
            margin-bottom: 0.5rem;
        }

        .sidebar-select, .sidebar-textarea {
            width: 100%;
            padding: 0.65rem;
            border-radius: 0.5rem;
            border: 1px solid var(--slate-600);
            background-color: var(--slate-900);
            color: white;
            font-size: 0.9rem;
            box-sizing: border-box;
        }
        
        .sidebar-textarea {
            resize: vertical;
            min-height: 400px;
			font-family: Arial, sans-serif;
			line-height: 1.6;
        }

        .collapsible-header {
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .collapsible-header .chevron {
            transition: transform 0.2s;
        }

        .collapsible-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
        }

        .collapsible-content.open {
            max-height: 800px; /* Increased to fit new content */
        }
        
        .slider-label-container {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.25rem;
        }
        
        .slider-label-container .value-display {
            font-size: 0.8rem;
            color: var(--slate-400);
            background-color: var(--slate-700);
            padding: 0.1rem 0.4rem;
            border-radius: 0.25rem;
        }

        .slider-container {
            margin-top: 1rem;
            padding-bottom: 0.5rem;
        }

        input[type="range"] {
            -webkit-appearance: none;
            width: 100%;
            background: transparent;
        }

        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            height: 16px;
            width: 16px;
            border-radius: 50%;
            background: var(--indigo-500);
            cursor: pointer;
            margin-top: -6px;
        }

        input[type="range"]::-webkit-slider-runnable-track {
            width: 100%;
            height: 4px;
            cursor: pointer;
            background: var(--slate-600);
            border-radius: 5px;
        }

        .chat-header {
            padding: 1rem 1.5rem;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            flex-shrink: 0;
            height: 32px;
        }
        
        .header-controls {
            display: flex;
            gap: 0.5rem;
        }

        .header-btn {
            background: none;
            border: 1px solid var(--slate-300);
            color: var(--slate-600);
            padding: 0.25rem 0.75rem;
            border-radius: 1rem;
            cursor: pointer;
            font-size: 0.8rem;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .header-btn:hover {
            background-color: var(--slate-100);
            border-color: var(--slate-400);
        }

        .message-container {
            flex-grow: 1;
            padding: 1.5rem;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .message {
            max-width: 75%;
            line-height: 1.5;
            word-wrap: break-word;
            display: flex;
            flex-direction: column;
        }

        .user-message {
            align-self: flex-end;
        }

        .ai-message {
            align-self: flex-start;
            background-color: var(--slate-100);
            color: var(--slate-800);
            border: 1px solid var(--slate-200);
            border-bottom-left-radius: 0.5rem;
            padding: 0.75rem 1.25rem;
            border-radius: 1.25rem;
        }
        
        .error-message {
            background-color: #fee2e2;
            color: #b91c1c;
            border-color: #fecaca;
        }

        .thinking {
            color: #888;
            font-style: italic;
            align-self: flex-start;
        }

        .message-image-container {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            justify-content: flex-end;
            margin-bottom: 0.5rem;
        }

        .message-image-container img {
            max-width: 100px;
            max-height: 100px;
            border-radius: 0.75rem;
            border: 2px solid var(--slate-200);
        }

        .text-bubble {
            background-color: var(--indigo-600);
            color: white;
            padding: 0.75rem 1.25rem;
            border-radius: 1.25rem;
            border-bottom-right-radius: 0.5rem;
            align-self: flex-end;
        }

        .chat-input-area {
            padding: 1rem 1.5rem;
            /*border-top: 1px solid var(--slate-200);*/
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            flex-shrink: 0;
        }

        .image-preview-container {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }

        .preview-wrapper {
            position: relative;
        }

        .preview-wrapper img {
            height: 60px;
            width: 60px;
            border-radius: 0.5rem;
            object-fit: cover;
            border: 2px solid var(--slate-300);
        }

        .remove-preview-btn {
            position: absolute;
            top: -5px;
            right: -5px;
            background-color: var(--red-500);
            color: white;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            border: none;
            font-weight: bold;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
        }

        .input-row {
            display: flex;
            align-items: center;
            gap: 1rem;
            width: 100%;
        }

        .attachment-btn {
            flex-shrink: 0;
            width: 48px;
            height: 48px;
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: var(--slate-200);
            color: var(--slate-600);
            border-radius: 50%;
            border: none;
            cursor: pointer;
            transition: background-color 0.2s;
        }

        .attachment-btn span {
            font-size: 1.75rem;
            line-height: 1;
            font-weight: 300;
        }

        .text-input-wrapper {
            flex-grow: 1;
            position: relative;
        }

        .text-input {
            width: 100%;
            padding: 0.75rem 1rem;
            border: 1px solid var(--slate-300);
            border-radius: 2rem;
            font-size: 1rem;
            resize: none;
            box-sizing: border-box;
        }

        .mic-btn {
            width: 60px;
            height: 60px;
            flex-shrink: 0;
            border-radius: 50%;
            border: none;
            background-color: var(--indigo-600);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: background-color 0.2s, transform 0.2s;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        }

        .mic-btn:hover {
            background-color: var(--indigo-700);
        }

        .mic-btn.listening {
            animation: pulse-blue 1.5s infinite;
        }

        @keyframes pulse-blue {
            0% {
                box-shadow: 0 0 0 0 rgba(79, 70, 229, 0.7);
            }
            70% {
                box-shadow: 0 0 0 10px rgba(79, 70, 229, 0);
            }
            100% {
                box-shadow: 0 0 0 0 rgba(79, 70, 229, 0);
            }
        }

        .tooltip-group {
            position: relative;
        }

        .custom-tooltip {
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            margin-bottom: 0.5rem;
            padding: 0.25rem 0.5rem;
            background-color: var(--slate-800);
            color: white;
            font-size: 0.75rem;
            border-radius: 0.375rem;
            white-space: nowrap;
            opacity: 0;
            transition: opacity 0.2s ease-in-out;
            pointer-events: none;
        }

        .tooltip-group:hover .custom-tooltip {
            opacity: 1;
        }

        .dropzone-overlay {
            position: absolute;
            inset: 0;
            background-color: rgba(15, 23, 42, 0.7);
            backdrop-filter: blur(4px);
            z-index: 200;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease-in-out;
        }

        .dropzone-overlay.visible {
            opacity: 1;
            pointer-events: auto;
        }

        .dropzone-content {
            text-align: center;
            color: white;
            border: 4px dashed white;
            border-radius: 1.5rem;
            padding: 3rem;
        }
        
        /* --- History Panel --- */
        #history-panel {
            position: absolute;
            top: 0;
            right: 0;
            bottom: 0;
            width: 320px;
            background-color: var(--slate-50);
            border-left: 1px solid var(--slate-300);
            z-index: 150;
            padding: 1.5rem;
            transform: translateX(100%);
            transition: transform 0.3s ease-in-out;
            display: flex;
            flex-direction: column;
        }
        
        #history-panel.open {
            transform: translateX(0);
        }
        
        .history-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }
        
        .history-list {
            flex-grow: 1;
            overflow-y: auto;
            margin-right: -10px;
            padding-right: 10px;
        }
        
        .history-item {
            padding: 0.75rem;
            background-color: white;
            border-radius: 0.5rem;
            cursor: pointer;
            border: 1px solid var(--slate-200);
            margin-bottom: 0.5rem;
            transition: background-color 0.2s, border-color 0.2s;
        }
        
        .history-item:hover {
            background-color: var(--slate-100);
            border-color: var(--slate-300);
        }
        
        .history-item-main {
             display: flex;
             justify-content: space-between;
             align-items: flex-start;
             gap: 0.5rem;
        }
        
        .history-item-title-container {
            flex-grow: 1;
            overflow: hidden;
        }

        .history-item-title {
            font-weight: 500;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            padding: 2px 0;
        }

        .history-item-title-input {
            width: 100%;
            font-size: 1em;
            font-weight: 500;
            border: 1px solid var(--indigo-500);
            border-radius: 0.25rem;
            padding: 1px;
            box-sizing: border-box;
        }
        
        .history-item-date {
            font-size: 0.75rem;
            color: var(--slate-500);
        }
        
        .history-item-controls {
            display: flex;
            align-items: center;
            flex-shrink: 0;
        }
        
        .history-control-btn {
            background: none;
            border: none;
            color: var(--slate-400);
            cursor: pointer;
            padding: 2px;
            display: flex;
            align-items: center;
        }
        
        .history-control-btn:hover {
            color: var(--slate-600);
        }
        
        .delete-history-btn:hover {
            color: var(--red-500);
        }

        .hidden {
            display: none !important;
        }

        .stop-btn {
            background-color: var(--red-500);
        }

        .stop-btn:hover {
            background-color: var(--red-600);
        }

        @media (max-width: 768px) {
            .main-content {
                padding: 0;
            }
            .chat-view {
                height: 100vh;
                max-height: none;
                border-radius: 0;
            }
            .sidebar {
                position: absolute;
                top: 0;
                left: 0;
                height: 100%;
                transform: translateX(-100%);
                width: 320px;
            }
            #history-panel {
                width: 300px;
            }
            .sidebar.open {
                transform: translateX(0);
            }
        }
    </style>
</head>
<body>
    <div class="app-container">
	
        <aside class="sidebar" id="sidebar">
		
            <div class="sidebar-section">
                <label for="model-selector">Select Model</label>
                <select id="model-selector" class="sidebar-select">
                    {% for model in model_list %}<option value="{{ model }}" {% if model == current_model %}selected{% endif %}>{{ model }}</option>{% endfor %}
                </select>
            </div>
			
            <div class="sidebar-section">
                <div class="collapsible-header" id="voice-settings-toggle">
                    <span>Voice Settings</span>
                    <span class="chevron">▼</span>
                </div>
                <div class="collapsible-content" id="voice-settings-content">
                    <div class="sidebar-section" style="margin-top: 1rem;">
                        <label for="tts-enabled-selector">Voice</label>
                        <select id="tts-enabled-selector" class="sidebar-select">
                            <option value="On">On</option>
                            <option value="Off">Off</option>
                        </select>
                    </div>
                    <div class="sidebar-section">
                        <label for="language-selector">Language</label>
                        <select id="language-selector" class="sidebar-select"></select>
                    </div>
                    <div class="sidebar-section">
                        <label for="voice-selector">Voice</label>
                        <select id="voice-selector" class="sidebar-select"></select>
                    </div>
                    <div class="slider-container">
                        <div class="slider-label-container">
                           <label for="speed-slider">Speech Speed</label>
                           <span id="speed-value" class="value-display">1.0x</span>
                        </div>
                        <input type="range" id="speed-slider" min="0.5" max="1.5" step="0.1">
                    </div>
                </div>
            </div>
            
            <div class="sidebar-section">
                <div class="collapsible-header" id="llm-settings-toggle">
                    <span>Model Parameters</span>
                    <span class="chevron">▼</span>
                </div>
                <div class="collapsible-content" id="llm-settings-content">
                    <div class="slider-container">
                        <div class="slider-label-container"><label for="num-ctx-slider">Context Size (Tokens)</label><span id="num-ctx-value" class="value-display">16000</span></div>
                        <input type="range" id="num-ctx-slider" min="0" max="128000" step="2000">
                    </div>
                    <div class="slider-container">
                        <div class="slider-label-container"><label for="temperature-slider">Temperature</label><span id="temperature-value" class="value-display">1.0</span></div>
                        <input type="range" id="temperature-slider" min="0" max="2" step="0.05">
                    </div>
                    <div class="slider-container">
                        <div class="slider-label-container"><label for="top-k-slider">Top K</label><span id="top-k-value" class="value-display">60</span></div>
                        <input type="range" id="top-k-slider" min="1" max="100" step="1">
                    </div>
                    <div class="slider-container">
                        <div class="slider-label-container"><label for="top-p-slider">Top P</label><span id="top-p-value" class="value-display">0.95</span></div>
                        <input type="range" id="top-p-slider" min="0" max="1" step="0.01">
                    </div>
                    <div class="slider-container">
                        <div class="slider-label-container"><label for="freq-penalty-slider">Frequency Penalty</label><span id="freq-penalty-value" class="value-display">1.0</span></div>
                        <input type="range" id="freq-penalty-slider" min="0" max="2" step="0.05">
                    </div>
                    <div class="slider-container">
                        <div class="slider-label-container"><label for="repeat-penalty-slider">Repeat Penalty</label><span id="repeat-penalty-value" class="value-display">1.0</span></div>
                        <input type="range" id="repeat-penalty-slider" min="0" max="2" step="0.05">
                    </div>
                </div>
            </div>
            
            <div class="sidebar-section">
                <div class="collapsible-header" id="system-message-toggle">
                    <span>System Message</span>
                    <span class="chevron">▼</span>
                </div>
                <div class="collapsible-content" id="system-message-content">
                    <div class="sidebar-section" style="margin-top: 1rem;">
                        <textarea id="system-message-input" class="sidebar-textarea">{{ saved_settings.system_message }}</textarea>
                    </div>
                </div>
            </div>
			
        </aside>
		
		
        <div class="main-content">
		
            <main class="chat-view" id="chat-view">
			
                <header class="chat-header">
                    <div class="header-controls">
                        <button class="header-btn" id="new-chat-btn">New Chat</button>
                        <button class="header-btn" id="history-btn">History</button>
                    </div>
                </header>
				
                <div id="welcome-screen" style="flex-grow: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: #94a3b8; padding: 1rem;">
                    <div>
                        <h1 style="font-size: 3.5rem; font-weight: 500; color: #cbd5e1; margin-bottom: 0;">myOfflineAi</h1>
                        <p style="font-size: 1.25rem; font-weight: 600; margin-top: 0.75rem; color: #64748b; margin-top: 0;">Voice Assistant</p>
						<!--
                        <p style="margin-top: 1rem; color: #64748b;">Attach a file or press the microphone to begin.</p>
						-->
                    </div>
                </div>
				
                <div class="message-container hidden" id="message-container">
                </div>
				
                <div class="chat-input-area">
                    <div id="image-preview-container" class="image-preview-container"></div>
                    <div class="input-row">
                        <input type="file" id="file-input" class="hidden" accept="image/*,.pdf" multiple>
                        <div class="tooltip-group">
                            <button class="attachment-btn" id="attachment-btn" type="button"><span>+</span></button>
                            <div class="custom-tooltip">png, jpg, pdf</div>
                        </div>
                        <div class="text-input-wrapper"><input class="text-input" id="text-input" placeholder="Talk or type..." autocomplete="off"></div>
                        <button class="mic-btn" id="mic-btn"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="22"></line></svg></button>
                        <button class="mic-btn stop-btn hidden" id="stop-audio-btn" title="Stop Playback"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h12v12H6z"></path></svg></button>
                    </div>
                </div>
				
                <div id="dropzone-overlay" class="dropzone-overlay">
                    <div class="dropzone-content">
                        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" /></svg>
                        <p>Drop Files Here</p>
                    </div>
                </div>
                
                <div id="history-panel">
                    <div class="history-header">
                        <h3 style="margin:0; color: var(--slate-700);">Chat History</h3>
                        <button id="close-history-btn" style="background:none; border:none; font-size: 1.5rem; cursor:pointer; color: var(--slate-500);">&times;</button>
                    </div>
                    <div class="history-list" id="history-list"></div>
                </div>
				
            </main>
        </div>
    </div>
	
    <audio id="audio-player" style="display: none;"></audio>
	
    <script>
    const ui = {
        sidebar: document.getElementById('sidebar'),
        voiceSettingsToggle: document.getElementById('voice-settings-toggle'),
        voiceSettingsContent: document.getElementById('voice-settings-content'),
        llmSettingsToggle: document.getElementById('llm-settings-toggle'),
        llmSettingsContent: document.getElementById('llm-settings-content'),
        systemMessageToggle: document.getElementById('system-message-toggle'),
        systemMessageContent: document.getElementById('system-message-content'),
        systemMessageInput: document.getElementById('system-message-input'),
        languageSelector: document.getElementById('language-selector'),
        voiceSelector: document.getElementById('voice-selector'),
        speedSlider: document.getElementById('speed-slider'),
        speedValue: document.getElementById('speed-value'),
        numCtxSlider: document.getElementById('num-ctx-slider'),
        numCtxValue: document.getElementById('num-ctx-value'),
        temperatureSlider: document.getElementById('temperature-slider'),
        temperatureValue: document.getElementById('temperature-value'),
        topKSlider: document.getElementById('top-k-slider'),
        topKValue: document.getElementById('top-k-value'),
        topPSlider: document.getElementById('top-p-slider'),
        topPValue: document.getElementById('top-p-value'),
        freqPenaltySlider: document.getElementById('freq-penalty-slider'),
        freqPenaltyValue: document.getElementById('freq-penalty-value'),
        repeatPenaltySlider: document.getElementById('repeat-penalty-slider'),
        repeatPenaltyValue: document.getElementById('repeat-penalty-value'),
        messageInput: document.getElementById('text-input'),
        micBtn: document.getElementById('mic-btn'),
        messageContainer: document.getElementById('message-container'),
        audioPlayer: document.getElementById('audio-player'),
        modelSelector: document.getElementById('model-selector'),
        attachmentBtn: document.getElementById('attachment-btn'),
        fileInput: document.getElementById('file-input'),
        previewContainer: document.getElementById('image-preview-container'),
        chatView: document.getElementById('chat-view'),
        dropzoneOverlay: document.getElementById('dropzone-overlay'),
        stopAudioBtn: document.getElementById('stop-audio-btn'),
        welcomeScreen: document.getElementById('welcome-screen'),
        newChatBtn: document.getElementById('new-chat-btn'),
        historyBtn: document.getElementById('history-btn'),
        historyPanel: document.getElementById('history-panel'),
        closeHistoryBtn: document.getElementById('close-history-btn'),
        historyList: document.getElementById('history-list'),
        ttsEnabledSelector: document.getElementById('tts-enabled-selector')
    };

    const ttsVoices = {
        'en-us': { name: 'American English', voices: { 'af_heart': 'Female', 'am_michael': 'Male' } },
        'en-gb': { name: 'British English', voices: { 'bf_emma': 'Female 1', 'bm_george': 'Male 1', 'if_sara': 'Female 2 (Italian)', 'im_nicola': 'Male 2 (Italian)' } },
        'zh': { name: 'Mandarin Chinese', voices: { 'zf_xiaoni': 'Female', 'zm_yunyang': 'Male' } },
        'es': { name: 'Spanish', voices: { 'ef_dora': 'Female', 'em_alex': 'Male' } },
        'fr': { name: 'French', voices: { 'ff_siwis': 'Female' } },
        'it': { name: 'Italian', voices: { 'if_sara': 'Female', 'im_nicola': 'Male' } },
        'pt-br': { name: 'Brazilian Portuguese', voices: { 'pf_dora': 'Female', 'pm_alex': 'Male' } }
    };

    const SILENCE_THRESHOLD = 0.01,
        SILENCE_TIMEOUT = 1500;
    let isRecording = false,
        isAiSpeaking = false,
        mediaRecorder, audioStream, audioContext, audioChunks = [],
        imageBase64Array = [],
        silenceTimer = null,
        conversationHistory = [],
        savedHistories = [],
        currentChatId = 'new',
        wasManuallyStopped = false,
        last_stt_duration = 0;
    let savedSettings = {{ saved_settings | tojson }};

    function updateVoiceOptions() {
        const langCode = ui.languageSelector.value;
        const voices = ttsVoices[langCode].voices;
        ui.voiceSelector.innerHTML = '';
        for (const voiceCode in voices) {
            const option = new Option(voices[voiceCode], voiceCode);
            ui.voiceSelector.add(option);
        }
    }
    
    async function saveAllSettings() {
        const settings = {
            model: ui.modelSelector.value,
            tts_lang: ui.languageSelector.value,
            tts_voice: ui.voiceSelector.value,
            tts_speed: ui.speedSlider.value,
            system_message: ui.systemMessageInput.value,
            temperature: ui.temperatureSlider.value,
            top_k: ui.topKSlider.value,
            top_p: ui.topPSlider.value,
            frequency_penalty: ui.freqPenaltySlider.value,
            repeat_penalty: ui.repeatPenaltySlider.value,
            num_ctx: ui.numCtxSlider.value,
            tts_enabled: ui.ttsEnabledSelector.value
        };
        try {
            await fetch('/save_settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
        } catch (error) {
            console.error('Error saving settings:', error);
        }
    }
    
    document.addEventListener('DOMContentLoaded', async () => {
        ui.micBtn.title = 'Start Listening';
        for (const langCode in ttsVoices) {
            const option = new Option(ttsVoices[langCode].name, langCode);
            ui.languageSelector.add(option);
        }
        
        applySettingsToUI(savedSettings);
        setupEventListeners();
        
        try {
            const res = await fetch("/conversations");
            if (!res.ok) throw new Error("Failed to load histories");
            savedHistories = await res.json();
        } catch (err) {
            console.error("Could not load saved conversations:", err);
        }
    });

    function setupCollapsible(toggle, content) {
        toggle.addEventListener('click', () => {
            content.classList.toggle('open');
            toggle.querySelector('.chevron').style.transform = content.classList.contains('open') ? 'rotate(180deg)' : 'rotate(0deg)';
        });
    }

    function setupEventListeners() {
        setupCollapsible(ui.voiceSettingsToggle, ui.voiceSettingsContent);
        setupCollapsible(ui.llmSettingsToggle, ui.llmSettingsContent);
        setupCollapsible(ui.systemMessageToggle, ui.systemMessageContent);

        ui.languageSelector.addEventListener('input', () => {
            updateVoiceOptions();
            saveAllSettings();
        });
        ui.voiceSelector.addEventListener('input', saveAllSettings);
        ui.systemMessageInput.addEventListener('input', saveAllSettings);
        ui.ttsEnabledSelector.addEventListener('input', saveAllSettings);
        
        const setupSliderListener = (slider, valueDisplay, formatFn) => {
            slider.addEventListener('input', () => {
                valueDisplay.textContent = formatFn(slider.value);
                saveAllSettings();
            });
        };
        
        setupSliderListener(ui.speedSlider, ui.speedValue, v => `${parseFloat(v).toFixed(1)}x`);
        setupSliderListener(ui.numCtxSlider, ui.numCtxValue, v => v);
        setupSliderListener(ui.temperatureSlider, ui.temperatureValue, v => parseFloat(v).toFixed(2));
        setupSliderListener(ui.topKSlider, ui.topKValue, v => v);
        setupSliderListener(ui.topPSlider, ui.topPValue, v => parseFloat(v).toFixed(2));
        setupSliderListener(ui.freqPenaltySlider, ui.freqPenaltyValue, v => parseFloat(v).toFixed(2));
        setupSliderListener(ui.repeatPenaltySlider, ui.repeatPenaltyValue, v => parseFloat(v).toFixed(2));

        ui.micBtn.addEventListener('click', toggleListening);
        ui.stopAudioBtn.addEventListener('click', stopAudioPlayback);
        ui.attachmentBtn.addEventListener('click', () => ui.fileInput.click());
        ui.fileInput.addEventListener('change', handleFileSelect);
        ui.messageInput.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitUserMessage();
            }
        });
        ui.modelSelector.addEventListener('change', () => {
            saveAllSettings();
        });
        ui.audioPlayer.addEventListener('ended', onAiSpeechEnd);
        ui.historyBtn.addEventListener('click', () => {
            renderSavedChatsList();
            ui.historyPanel.classList.add('open');
        });
        ui.closeHistoryBtn.addEventListener('click', () => ui.historyPanel.classList.remove('open'));
        ui.newChatBtn.addEventListener('click', startNewChat);

        let dragCounter = 0;
        ui.chatView.addEventListener('dragenter', e => { e.preventDefault(); e.stopPropagation(); if (isRecording) return; dragCounter++; if (dragCounter === 1) ui.dropzoneOverlay.classList.add('visible'); });
        ui.chatView.addEventListener('dragleave', e => { e.preventDefault(); e.stopPropagation(); dragCounter--; if (dragCounter === 0) ui.dropzoneOverlay.classList.remove('visible'); });
        ui.chatView.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); });
        ui.chatView.addEventListener('drop', e => {
            e.preventDefault();
            e.stopPropagation();
            if (isRecording) return;
            dragCounter = 0;
            ui.dropzoneOverlay.classList.remove('visible');
            if (e.dataTransfer.files.length > 0) {
                ui.fileInput.files = e.dataTransfer.files;
                ui.fileInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });
    }

    async function startNewChat() {
        conversationHistory = [];
        currentChatId = 'new';
        ui.messageContainer.innerHTML = '';
        ui.welcomeScreen.classList.remove('hidden');
        ui.messageContainer.classList.add('hidden');
        ui.historyPanel.classList.remove('open');
        
        try {
            console.log("Fetching latest settings for new chat...");
            const res = await fetch('/get_settings');
            if (!res.ok) throw new Error('Failed to fetch settings from server.');
            const latestSettings = await res.json();
            savedSettings = latestSettings; // Update the global JS settings object
            applySettingsToUI(savedSettings);
            console.log("Successfully loaded and applied latest settings.");
        } catch (error) {
            console.error("Could not reload settings:", error);
            // Fallback to the settings that were loaded with the page
            applySettingsToUI(savedSettings);
        }
    }

    function submitUserMessage() {
        const text = ui.messageInput.value.trim();
        if ((!text && imageBase64Array.length === 0) || isAiSpeaking || isRecording) return;
        last_stt_duration = 0; // No STT for text input
        const userMessage = {
            role: 'user',
            content: text,
            ...(imageBase64Array.length > 0 && { images: [...imageBase64Array] })
        };
        addMessage(userMessage);
        conversationHistory.push(userMessage);
        ui.messageInput.value = '';
        imageBase64Array = [];
        updatePreviews();
        sendTextToServer();
    }
    
    function toggleListening() {
        if (isAiSpeaking) return;
        const isNowListening = ui.micBtn.classList.toggle('listening');
        ui.micBtn.title = isNowListening ? "Stop Listening" : "Start Listening";
        if (isNowListening) {
            ui.messageInput.value = '';
            startRecording();
        } else {
            stopRecording(true);
        }
    }
	
    async function startRecording() {
        console.log("Recording started...");
        if (isRecording) return;
        ui.chatView.classList.add('mic-active-shadow');
        setControlsEnabled(false, { keepMicActive: true });
        try {
            audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            isRecording = true;
            mediaRecorder = new MediaRecorder(audioStream);
            audioChunks = [];
            mediaRecorder.start();
            mediaRecorder.addEventListener("dataavailable", e => audioChunks.push(e.data));
            mediaRecorder.addEventListener("stop", onRecordingStop);
            audioContext = new AudioContext();
            const source = audioContext.createMediaStreamSource(audioStream);
            const analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;
            const dataArray = new Uint8Array(analyser.frequencyBinCount);
            source.connect(analyser);
            detectSilence(analyser, dataArray);
        } catch (err) {
            handleError("Could not access microphone. Please check permissions.");
        }
    }

    function detectSilence(analyser, dataArray) {
        if (!isRecording) return;
        analyser.getByteTimeDomainData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += Math.abs((dataArray[i] / 128.0) - 1.0);
        if (sum / dataArray.length > SILENCE_THRESHOLD) {
            if (silenceTimer) clearTimeout(silenceTimer);
            silenceTimer = null;
        } else if (!silenceTimer) {
            silenceTimer = setTimeout(() => {
			    console.log("Silence detected, stopping recording.");
			    stopRecording(false);
			}, SILENCE_TIMEOUT);
        }
        requestAnimationFrame(() => detectSilence(analyser, dataArray));
    }

    function stopRecording(isManualStop) {
        if (!isRecording) return;
        if (isManualStop) { wasManuallyStopped = true; }
        isRecording = false;
        mediaRecorder?.stop();
        audioStream?.getTracks().forEach(track => track.stop());
        audioContext?.close();
        clearTimeout(silenceTimer);
        if (isManualStop) {
            ui.micBtn.classList.remove('listening');
            ui.micBtn.title = 'Start Listening';
            ui.chatView.classList.remove('mic-active-shadow');
            setControlsEnabled(true);
        }
    }

    function onRecordingStop() {
        if (wasManuallyStopped) {
            wasManuallyStopped = false;
            audioChunks = [];
            return;
        }
        if (audioChunks.length < 1) return;
        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
        if (audioBlob.size < 1000) {
            if (ui.micBtn.classList.contains('listening')) startRecording();
            return;
        }
        sendAudioToServer(audioBlob);
    }
    
    async function sendAudioToServer(audioBlob) {
        setControlsEnabled(false);
        const formData = new FormData();
        formData.append('audio_data', audioBlob, 'recording.wav');
        formData.append('images', JSON.stringify(imageBase64Array));
        formData.append('language', ui.languageSelector.value);
        try {
            const response = await fetch('/transcribe', { method: 'POST', body: formData });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || `Transcription error: ${response.statusText}`);
            
            last_stt_duration = data.stt_duration || 0;
            if (data.status === 'no_speech' && imageBase64Array.length === 0) {
                if (ui.micBtn.classList.contains('listening')) startRecording();
                else setControlsEnabled(true);
                return;
            }
            const userMessage = {
                role: 'user',
                content: data.transcribedText,
                ...(imageBase64Array.length > 0 && { images: [...imageBase64Array] })
            };
            addMessage(userMessage);
            conversationHistory.push(userMessage);
            imageBase64Array = [];
            updatePreviews();
            sendTextToServer();
        } catch (error) {
            handleError(error.message);
        }
    }
    
    async function sendTextToServer() {
        setControlsEnabled(false);
        const thinkingIndicator = addMessage({ role: 'thinking', content: 'Processing...' });
        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    history: conversationHistory,
                    model: ui.modelSelector.value,
                    tts_voice: ui.voiceSelector.value,
                    tts_speed: ui.speedSlider.value,
                    tts_lang: ui.languageSelector.value,
                    stt_duration: last_stt_duration,
                    system_message: ui.systemMessageInput.value,
                    llm_options: {
                        temperature: ui.temperatureSlider.value,
                        top_k: ui.topKSlider.value,
                        top_p: ui.topPSlider.value,
                        frequency_penalty: ui.freqPenaltySlider.value,
                        repeat_penalty: ui.repeatPenaltySlider.value,
                        num_ctx: ui.numCtxSlider.value
                    },
                    tts_enabled: ui.ttsEnabledSelector.value
                })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || `Server error: ${response.statusText}`);
            handleAiResponse(data, thinkingIndicator);
        } catch (error) {
            handleError(error.message, thinkingIndicator);
        } finally {
            last_stt_duration = 0;
        }
    }

    async function handleAiResponse(data, thinkingIndicator) {
        thinkingIndicator.remove();
        ui.chatView.classList.remove('mic-active-shadow');
        const aiMessage = { role: 'assistant', content: data.responseText };
        addMessage(aiMessage);
        conversationHistory.push(aiMessage);
        
        await saveOrUpdateCurrentChat();
        
        if (data.warning) setTimeout(() => alert(data.warning), 500);

        if (ui.ttsEnabledSelector.value === 'On' && data.audioData) {
            isAiSpeaking = true;
            ui.micBtn.classList.add('hidden');
            ui.stopAudioBtn.classList.remove('hidden');
            ui.audioPlayer.src = `data:audio/wav;base64,${data.audioData}`;
            const playPromise = ui.audioPlayer.play();
            if (playPromise !== undefined) {
                playPromise.catch(error => {
                    console.error("Audio playback failed:", error);
                    onAiSpeechEnd();
                });
            }
        } else {
            onAiSpeechEnd();
        }
    }

    function stopAudioPlayback() {
        ui.audioPlayer.pause();
        ui.audioPlayer.currentTime = 0;
        onAiSpeechEnd();
    }

    function onAiSpeechEnd() {
        isAiSpeaking = false;
        ui.micBtn.classList.remove('hidden');
        ui.stopAudioBtn.classList.add('hidden');
        
        // Always re-enable the main controls first.
        setControlsEnabled(true);

        // If the mic was in a 'continuous listening' state before the AI spoke, restart recording.
        // startRecording() will correctly disable the text input again.
        if (ui.micBtn.classList.contains('listening')) {
            startRecording();
        }
    }

    function handleError(errorMessage, indicator) {
        console.error('Error:', errorMessage);
        if (indicator) indicator.remove();
        addMessage({ role: 'assistant', content: errorMessage || 'Sorry, an unknown error occurred.', isError: true });
        if (conversationHistory.length > 0 && conversationHistory[conversationHistory.length - 1].role === 'user') {
            conversationHistory.pop();
        }
        if (isRecording) stopRecording(true);
        onAiSpeechEnd(); // Ensure controls are re-enabled
    }

    function handleFileSelect(event) {
        const files = event.target.files;
        if (!files) return;
        const filePromises = Array.from(files).map(file => new Promise(async (resolve, reject) => {
            if (file.type === 'application/pdf') {
                const formData = new FormData();
                formData.append('pdf_file', file);
                try {
                    const response = await fetch('/upload_pdf', { method: 'POST', body: formData });
                    const result = await response.json();
                    if (response.ok) resolve(result.images);
                    else reject(new Error(result.error || 'Failed to convert PDF.'));
                } catch (error) {
                    reject(error);
                }
            } else {
                const reader = new FileReader();
                reader.onload = () => resolve([reader.result]);
                reader.onerror = reject;
                reader.readAsDataURL(file);
            }
        }));
        Promise.all(filePromises).then(results => {
            imageBase64Array.push(...results.flat());
            updatePreviews();
            ui.fileInput.value = '';
        }).catch(error => alert(`Error: ${error.message}`));
    }

    function updatePreviews() {
        ui.previewContainer.innerHTML = '';
        imageBase64Array.forEach((base64String, index) => {
            const wrapper = document.createElement('div');
            wrapper.className = 'preview-wrapper';
            wrapper.innerHTML = `<img src="${base64String}"><button type="button" class="remove-preview-btn">&times;</button>`;
            wrapper.querySelector('button').onclick = () => {
                imageBase64Array.splice(index, 1);
                updatePreviews();
            };
            ui.previewContainer.appendChild(wrapper);
        });
    }

    function addMessage(msg) {
        if (ui.welcomeScreen && !ui.welcomeScreen.classList.contains('hidden')) {
            ui.welcomeScreen.classList.add('hidden');
            ui.messageContainer.classList.remove('hidden');
        }
        const el = document.createElement('div');
        el.classList.add('message');
        if (msg.role === 'user') {
            el.classList.add('user-message');
            if (msg.images?.length > 0) {
                const imgContainer = document.createElement('div');
                imgContainer.className = 'message-image-container';
                msg.images.forEach(src => {
                    const img = document.createElement('img');
                    img.src = src;
                    imgContainer.appendChild(img);
                });
                el.appendChild(imgContainer);
            }
            if (msg.content) {
                const textBubble = document.createElement('div');
                textBubble.className = 'text-bubble';
                textBubble.textContent = msg.content;
                el.appendChild(textBubble);
            }
        } else {
            el.classList.add(msg.role === 'assistant' ? 'ai-message' : 'thinking');
            if (msg.isError) {
                el.classList.add('error-message');
            }
            el.textContent = msg.content;
        }
        ui.messageContainer.appendChild(el);
        ui.messageContainer.scrollTop = ui.messageContainer.scrollHeight;
        return el;
    }
    
    function renderConversation(history) {
        ui.messageContainer.innerHTML = '';
        history.forEach(msg => addMessage(msg));
    }

    function setControlsEnabled(enabled, { keepMicActive = false } = {}) {
        ui.messageInput.disabled = !enabled;
        ui.attachmentBtn.disabled = !enabled;
        ui.micBtn.disabled = keepMicActive ? false : !enabled;
        if (enabled) ui.messageInput.focus();
    }
    
    // --- Settings and History Functions ---
    
    function applySettingsToUI(settings) {
        const updateSlider = (slider, valueDisplay, value, formatFn) => {
            slider.value = value;
            valueDisplay.textContent = formatFn(value);
        };

        ui.systemMessageInput.value = settings.system_message;
        ui.modelSelector.value = settings.model;
        ui.ttsEnabledSelector.value = settings.tts_enabled;

        ui.languageSelector.value = settings.tts_lang;
        updateVoiceOptions();
        ui.voiceSelector.value = settings.tts_voice;
        updateSlider(ui.speedSlider, ui.speedValue, settings.tts_speed, v => `${parseFloat(v).toFixed(1)}x`);

        updateSlider(ui.numCtxSlider, ui.numCtxValue, settings.num_ctx, v => v);
        updateSlider(ui.temperatureSlider, ui.temperatureValue, settings.temperature, v => parseFloat(v).toFixed(2));
        updateSlider(ui.topKSlider, ui.topKValue, settings.top_k, v => v);
        updateSlider(ui.topPSlider, ui.topPValue, settings.top_p, v => parseFloat(v).toFixed(2));
        updateSlider(ui.freqPenaltySlider, ui.freqPenaltyValue, settings.frequency_penalty, v => parseFloat(v).toFixed(2));
        updateSlider(ui.repeatPenaltySlider, ui.repeatPenaltyValue, settings.repeat_penalty, v => parseFloat(v).toFixed(2));
    }

    function getCurrentUISettings() {
        return {
            model: ui.modelSelector.value,
            system_message: ui.systemMessageInput.value,
            tts_lang: ui.languageSelector.value,
            tts_voice: ui.voiceSelector.value,
            tts_speed: ui.speedSlider.value,
            temperature: ui.temperatureSlider.value,
            top_k: ui.topKSlider.value,
            top_p: ui.topPSlider.value,
            frequency_penalty: ui.freqPenaltySlider.value,
            repeat_penalty: ui.repeatPenaltySlider.value,
            num_ctx: ui.numCtxSlider.value,
            tts_enabled: ui.ttsEnabledSelector.value
        };
    }

    async function saveOrUpdateCurrentChat() {
        if (!conversationHistory || conversationHistory.length === 0) return;
        const currentSettings = getCurrentUISettings();

        if (currentChatId === 'new') {
            const firstUserMessage = conversationHistory.find(m => m.role === 'user');
            const title = firstUserMessage ? (firstUserMessage.content || 'Image Query').substring(0, 40) : 'Untitled Chat';

            const newChatSession = {
                id: `chat-${Date.now()}`,
                timestamp: new Date().toISOString(),
                title: title,
                history: conversationHistory,
                settings: currentSettings
            };

            try {
                const res = await fetch(`/conversations`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newChatSession)
                });
                const savedSession = await res.json();
                if (res.ok) {
                    savedHistories.unshift(savedSession);
                    currentChatId = savedSession.id;
                }
            } catch (err) { console.error('Error saving new chat session:', err); }
        } else {
            try {
                const res = await fetch(`/conversations/${currentChatId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ history: conversationHistory, settings: currentSettings })
                });

                if (res.ok) {
                    const chatIndex = savedHistories.findIndex(c => c.id === currentChatId);
                    if (chatIndex !== -1) {
                        const updatedChat = savedHistories[chatIndex];
                        updatedChat.history = conversationHistory;
                        updatedChat.settings = currentSettings;
                        updatedChat.timestamp = new Date().toISOString();
                        savedHistories.splice(chatIndex, 1);
                        savedHistories.unshift(updatedChat);
                    }
                }
            } catch (err) { console.error('Error updating chat session:', err); }
        }
    }
    
    function renderSavedChatsList() {
        ui.historyList.innerHTML = '';
        if (savedHistories.length === 0) {
            ui.historyList.innerHTML = `<p style="text-align:center; color: var(--slate-500); font-size: 0.9rem;">No saved chats.</p>`;
            return;
        }

        savedHistories.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        savedHistories.forEach(chat => {
            const itemEl = document.createElement('div');
            itemEl.className = 'history-item';
            itemEl.innerHTML = `
                <div class="history-item-main">
                    <div class="history-item-title-container">
                        <div class="history-item-title" title="${chat.title}">${chat.title}</div>
                        <input type="text" class="history-item-title-input hidden" value="${chat.title}">
                        <p class="history-item-date">${new Date(chat.timestamp).toLocaleString()}</p>
                    </div>
                    <div class="history-item-controls">
                        <button class="history-control-btn edit-history-btn" data-chat-id="${chat.id}">
						
                           <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
							  <path d="M15.502 1.94a.5.5 0 0 1 0 .706L14.459 3.69l-2-2L13.502.646a.5.5 0 0 1 .707 0l1.293 1.293zm-1.75 2.456-2-2L4.939 9.21a.5.5 0 0 0-.121.196l-.805 2.414a.25.25 0 0 0 .316.316l2.414-.805a.5.5 0 0 0 .196-.12l6.813-6.814z"/>
							  <path fill-rule="evenodd" d="M1 13.5A1.5 1.5 0 0 0 2.5 15h11a1.5 1.5 0 0 0 1.5-1.5v-6a.5.5 0 0 0-1 0v6a.5.5 0 0 1-.5.5h-11a.5.5 0 0 1-.5-.5v-11a.5.5 0 0 1 .5-.5H9a.5.5 0 0 0 0-1H2.5A1.5 1.5 0 0 0 1 2.5z"/>
							</svg>
							
                        </button>
                        <button class="history-control-btn delete-history-btn" data-chat-id="${chat.id}">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5m2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5m3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0z"/><path d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4zM2.5 3h11V2h-11z"/></svg>
                        </button>
                    </div>
                </div>
            `;
            itemEl.onclick = (e) => {
                if (e.target.closest('.history-control-btn')) return;
                loadChatHistory(chat.id);
            };

            const titleDiv = itemEl.querySelector('.history-item-title');
            const titleInput = itemEl.querySelector('.history-item-title-input');

            const saveTitle = async () => {
                const newTitle = titleInput.value.trim();
                const originalTitle = titleDiv.textContent;
                if (newTitle && newTitle !== originalTitle) {
                    try {
                        await updateChatTitle(chat.id, newTitle);
                        titleDiv.textContent = newTitle;
                        titleDiv.title = newTitle;
                        const chatInHistory = savedHistories.find(c => c.id === chat.id);
                        if (chatInHistory) chatInHistory.title = newTitle;
                    } catch (err) {
                        alert("Failed to update title.");
                        titleInput.value = originalTitle; // Revert on failure
                    }
                } else {
                    titleInput.value = originalTitle;
                }
                 // Switch back to view mode
                titleDiv.classList.remove('hidden');
                titleInput.classList.add('hidden');
            };

            itemEl.querySelector('.edit-history-btn').onclick = (e) => {
                e.stopPropagation();
                titleDiv.classList.add('hidden');
                titleInput.classList.remove('hidden');
                titleInput.focus();
                titleInput.select();
            };

            titleInput.onkeydown = (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    titleInput.blur(); // Triggers the save
                } else if (e.key === 'Escape') {
                    titleInput.value = titleDiv.textContent; // Revert
                    titleInput.blur();
                }
            };
            titleInput.onblur = saveTitle;

            itemEl.querySelector('.delete-history-btn').onclick = (e) => {
                e.stopPropagation();
                if (confirm('Delete this chat history forever?')) {
                    deleteChatHistory(chat.id);
                }
            };
            ui.historyList.appendChild(itemEl);
        });
    }

    function loadChatHistory(chatId) {
        const chatToLoad = savedHistories.find(c => c.id === chatId);
        if (chatToLoad) {
            if (chatToLoad.settings) {
                applySettingsToUI(chatToLoad.settings);
            }
            conversationHistory = JSON.parse(JSON.stringify(chatToLoad.history));
            currentChatId = chatToLoad.id;
            renderConversation(conversationHistory);
            ui.historyPanel.classList.remove('open');
        }
    }

    async function deleteChatHistory(chatId) {
        try {
            const res = await fetch(`/conversations/${chatId}`, { method: 'DELETE' });
            if (res.ok) {
                savedHistories = savedHistories.filter(c => c.id !== chatId);
                renderSavedChatsList();
                if (currentChatId === chatId) {
                    startNewChat();
                }
            } else {
                alert('Failed to delete chat history.');
            }
        } catch (err) {
            alert('Error deleting chat history.');
        }
    }

    async function updateChatTitle(chatId, newTitle) {
        const res = await fetch(`/conversations/${chatId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        });
        if (!res.ok) {
            throw new Error("Failed to update title on server.");
        }
    }
    </script>
</body>
</html>
"""



@app.route("/")
def index():
    # Load the latest settings from the file every time the page is requested.
    current_user_settings = load_settings()
    
    # PRIVACY FEATURE: Set security headers to prevent caching and enhance security.
    template = render_template_string(HTML_TEMPLATE, model_list=model_list, current_model=OLLAMA_MODEL, saved_settings=current_user_settings)
    response = Response(template)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response
	
	

@app.route("/get_settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())

@app.route("/save_settings", methods=["POST"])
def save_all_settings():
    global OLLAMA_MODEL
    new_settings = request.json
    
    # Update the global model variable if it has changed
    new_model = new_settings.get("model")
    if new_model and new_model in model_list and new_model != OLLAMA_MODEL:
        OLLAMA_MODEL = new_model
        print(f"[INFO] Model changed to: {OLLAMA_MODEL}")

    settings = load_settings()
    settings.update(new_settings)
    save_settings(settings)
    print(f"[INFO] Saved new settings.")
    return jsonify({"status": "success"})
	
	

@app.route("/upload_pdf", methods=["POST"])
def upload_pdf():
    if 'pdf_file' not in request.files: return jsonify({"error": "No PDF file part."}), 400
    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '': return jsonify({"error": "No selected file."}), 400
    try:
        doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
        if len(doc) > MAX_PAGES: return jsonify({"error": f"PDF exceeds {MAX_PAGES} pages."}), 400
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(PDF_IMAGE_RES, PDF_IMAGE_RES))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            byte_io = io.BytesIO()
            img.save(byte_io, 'JPEG', quality=90)
            images.append(f"data:image/jpeg;base64,{base64.b64encode(byte_io.getvalue()).decode('utf-8')}")
        doc.close()
        return jsonify({"images": images})
    except Exception as e:
        return jsonify({"error": f"Failed to process PDF: {str(e)}"}), 500
		
		
		
@app.route("/transcribe", methods=["POST"])
def transcribe_audio():
    if 'audio_data' not in request.files: return jsonify({"error": "No audio file."}), 400
    temp_audio_path = "temp_recording.wav"
    try:
        audio_file = request.files['audio_data']
        audio_file.save(temp_audio_path)
        
        lang = request.form.get('language', 'en')
        lang_code = lang.split('-')[0]
        
        # --- Whisper STT Timing ---
        start_time = time.time()
        result = whisper_model.transcribe(temp_audio_path, fp16=False, language=lang_code)
        stt_duration = time.time() - start_time
        # --- End Timing ---
        
        user_transcript = result["text"].strip()
        print(f"[INFO] Transcribed text ('{lang_code}'): '{user_transcript}'")

        if has_repeated_phrases(user_transcript) or contains_mixed_scripts(user_transcript):
            print(f"[INFO] Garbled text detected and discarded: '{user_transcript}'")
            user_transcript = ""

        if not user_transcript and not json.loads(request.form.get('images', '[]')):
             return jsonify({"status": "no_speech"})
        
        return jsonify({
            "transcribedText": user_transcript,
            "stt_duration": stt_duration
        })
    except Exception as e:
        print(f"[ERROR] /transcribe error: {e}", file=sys.stderr)
        return jsonify({"error": "Internal server error."}), 500
    finally:
        if os.path.exists(temp_audio_path): os.remove(temp_audio_path)
		
		
		
@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        history = data.get("history", [])
        stt_duration = data.get("stt_duration", 0)
        system_message = data.get("system_message", DEFAULT_SYSTEM_MESSAGE)
        llm_options = data.get("llm_options", {})
        tts_enabled = data.get("tts_enabled", "On")
        
        if not history or history[-1]['role'] != 'user': return jsonify({"error": "Invalid history."}), 400
        
        ai_text_response, audio_base64, warning_msg, inference_duration, tts_duration = process_chat_and_get_audio(
            history, 
            data.get("model", OLLAMA_MODEL),
            data.get("tts_voice"),
            data.get("tts_speed"),
            data.get("tts_lang"),
            system_message,
            llm_options,
            tts_enabled
        )

        # Calculate and print all timings at the end of the turn
        total_duration = stt_duration + inference_duration + tts_duration
        print("\n--- Timing Report ---")
        print(f"STT (Whisper):      {stt_duration:.2f}s")
        print(f"Inference (Ollama): {inference_duration:.2f}s")
        print(f"TTS (Kokoro):       {tts_duration:.2f}s")
        print("---------------------")
        print(f"Total Time:         {total_duration:.2f}s\n")


        response_data = {"responseText": ai_text_response, "audioData": audio_base64}
        if warning_msg: response_data["warning"] = warning_msg
        return jsonify(response_data)
    except ConnectionError as e:
        # Catches the specific error raised when Ollama is unreachable.
        print(f"[ERROR] /chat endpoint connection error: {e}", file=sys.stderr)
        # 503 Service Unavailable is an appropriate HTTP status code
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        print(f"[ERROR] /chat endpoint error: {e}", file=sys.stderr)
        return jsonify({"error": "An internal server error occurred."}), 500
		
		
# --- Conversation History Routes ---

@app.route("/conversations", methods=["GET"])
def get_all_conversations():
    return jsonify(load_conversations())

@app.route("/conversations", methods=["POST"])
def save_new_conversation():
    new_chat_session = request.json
    if not all(k in new_chat_session for k in ['id', 'timestamp', 'title', 'history', 'settings']):
        return jsonify({"error": "Invalid chat session format"}), 400
    
    conversations = load_conversations()
    conversations.insert(0, new_chat_session)
    save_conversations(conversations)
    return jsonify(new_chat_session), 201

@app.route("/conversations/<chat_id>", methods=["PUT"])
def update_existing_conversation(chat_id):
    updated_data = request.json
    conversations = load_conversations()
    chat_index = next((i for i, chat in enumerate(conversations) if chat.get('id') == chat_id), -1)

    if chat_index != -1:
        updated = False
        # Handle full history/settings update
        if 'history' in updated_data and 'settings' in updated_data:
            conversations[chat_index]['history'] = updated_data['history']
            conversations[chat_index]['settings'] = updated_data['settings']
            updated = True
        
        # Handle title-only update
        if 'title' in updated_data:
            new_title = updated_data['title'].strip()
            if new_title:
                conversations[chat_index]['title'] = new_title
                updated = True

        if updated:
            conversations[chat_index]['timestamp'] = datetime.now(timezone.utc).isoformat()
            # Move the updated chat to the top of the list
            updated_chat = conversations.pop(chat_index)
            conversations.insert(0, updated_chat)
            save_conversations(conversations)
            return jsonify({"status": "updated"})
        
        return jsonify({"error": "No valid update data provided"}), 400
        
    return jsonify({"error": "History not found"}), 404

@app.route("/conversations/<chat_id>", methods=["DELETE"])
def delete_existing_conversation(chat_id):
    conversations = load_conversations()
    initial_len = len(conversations)
    conversations = [chat for chat in conversations if chat.get('id') != chat_id]
    if len(conversations) < initial_len:
        save_conversations(conversations)
        return jsonify({"status": "deleted"})
    return jsonify({"error": "History not found"}), 404
		
	
	

if __name__ == "__main__":
	
    try:
        print(f"[INFO] Checking for selected model: '{OLLAMA_MODEL}'")
        ollama.show(OLLAMA_MODEL)
        print("[INFO] Model found.")
    except Exception:
        print(f"[ERROR] Could not connect to Ollama or find model '{OLLAMA_MODEL}'. Please ensure Ollama is running and the model is downloaded.", file=sys.stderr)
        sys.exit(1)
		
    import webbrowser, threading
	
    server_url = "http://127.0.0.1:5000"

    def open_browser():
        """Opens the default web browser to the server's URL."""
        print(f"[INFO] Attempting to open browser at {server_url}")
        webbrowser.open(server_url)

    # This check prevents the browser from opening twice when the Flask reloader is active.
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        print(f"[INFO] Starting Flask server. If the browser does not open automatically, please navigate to: {server_url}")
        # Start a timer to open the browser after a short delay, allowing the server to start.
        threading.Timer(1.5, open_browser).start()
		
    app.run(host="127.0.0.1", port=5000, debug=False)