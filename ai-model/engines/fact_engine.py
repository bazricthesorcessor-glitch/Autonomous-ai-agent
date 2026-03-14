import json
import os
import re
import tempfile
import threading
from datetime import datetime
import config
from ollama import Client

client = Client(host='http://localhost:11434')
FACTS_PATH = config.FACTS_FILE
_facts_lock = threading.Lock()

# STRICT TAXONOMY
ALLOWED_CATEGORIES = [
    "name", "os", "location", "language",
    "dog", "favorite_anime", "job", "project", "user"
]

# Fast pre-filter: only call LLM when message likely contains a fact
_FACT_SIGNALS = re.compile(
    r'\b(?:my name|i am|i\'m|i live|i moved|i have|i got|i lost|i sold|'
    r'i work|i use|i run|my dog|my cat|my pet|my job|my project|'
    r'my fav|i like|i love|i prefer|i switched|i bought|died|passed away)\b',
    re.IGNORECASE,
)

def load_facts():
    if not os.path.exists(FACTS_PATH):
        return {}
    try:
        with open(FACTS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_facts(data):
    dir_name = os.path.dirname(FACTS_PATH) or '.'
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, FACTS_PATH)
    except Exception:
        os.unlink(tmp)
        raise

def update_fact(category, value):
    with _facts_lock:
        facts = load_facts()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if category not in facts:
            facts[category] = {"current": None, "history": []}

        if facts[category]["current"] is not None:
            facts[category]["history"].append({
                "value": facts[category]["current"],
                "valid_to": now
            })

        facts[category]["current"] = value
        save_facts(facts)
        print(f"[Fact Engine] Updated {category}: {value}")

def forget_fact(category):
    with _facts_lock:
        facts = load_facts()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if category in facts and facts[category]["current"] is not None:
            facts[category]["history"].append({
                "value": facts[category]["current"],
                "valid_to": now,
                "status": "forgotten"
            })
            facts[category]["current"] = None
            save_facts(facts)
            print(f"[Fact Engine] Forgot {category}")

def get_active_facts():
    facts = load_facts()
    return {k: v["current"] for k, v in facts.items() if v["current"] is not None}

def process_fact_query(query):
    # Fast exit: skip LLM call if message doesn't look like a factual statement
    if not _FACT_SIGNALS.search(query):
        return

    prompt = f"""You are a structured data extractor.
Extract facts from the statement.

ALLOWED CATEGORIES:
{json.dumps(ALLOWED_CATEGORIES)}

CURRENT FACTS:
{json.dumps(get_active_facts())}

USER INPUT:
"{query}"

TASK:
- Extract updates.
- Detect loss (e.g., "died", "sold", "lost") -> action "forget".
- Use ONLY allowed categories.

OUTPUT FORMAT:
{{
  "facts": [
    {{"action": "update", "category": "key", "value": "value"}},
    {{"action": "forget", "category": "key"}}
  ]
}}
"""

    try:
        response = client.chat(
            model=config.CHAT_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            format='json',
            options={
                "temperature": 0.0,
                "top_p": 0.1
            }
        )
        content = response['message']['content']

        data = json.loads(content)

        if not isinstance(data, dict): return
        facts_list = data.get("facts", [])
        if not isinstance(facts_list, list): return

        for item in facts_list:
            action = item.get("action")
            cat = item.get("category")
            val = item.get("value")

            if cat not in ALLOWED_CATEGORIES:
                print(f"[Fact Engine] Rejected invalid category: {cat}")
                continue

            if action == "update" and cat and val:
                update_fact(cat, val)
            elif action == "forget" and cat:
                forget_fact(cat)

    except json.JSONDecodeError:
        print("[Fact Engine] JSON Parse Error.")
    except Exception as e:
        print(f"[Fact Engine] Error: {e}")
