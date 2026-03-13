import json
from ollama import Client
import config

client = Client(host='http://localhost:11434')

AVAILABLE_MODELS = [
    "phi3:latest",
    config.CHAT_MODEL,
    config.CODE_MODEL,
    "dolphin-mistral:latest"
]

SYSTEM_PROMPT = """
You are a BRAIN ROUTER. You do not chat.
Output ONLY the model name best suited for the task.

RULES:
1. "phi3:latest" -> Math, logic, reasoning.
2. "llama3.2:3b" -> General chat, creative writing, roleplay, summaries.
3. "qwen2.5-coder:7b-instruct-q4_K_M" -> ANY code, python, scripts, algorithms.
4. "dolphin-mistral:latest" -> Uncensored specific requests.

Output ONLY the model name string. No explanation.
"""

def route(user_input):
    try:
        response = client.chat(
            model=config.DECISION_MODEL,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': user_input}
            ],
            options={'temperature': 0.0, 'num_predict': 50}
        )

        model_name = response['message']['content'].strip()

        for m in AVAILABLE_MODELS:
            if m in model_name:
                return m

        return config.CHAT_MODEL

    except Exception as e:
        print(f"[Brain Error]: {e}")
        return config.CHAT_MODEL

def initialize_brain():
    print("[System] Brain Signal Online.")
