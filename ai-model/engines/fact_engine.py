import json
import os
from datetime import datetime
import config
from ollama import Client

client = Client(host='http://localhost:11434')
FACTS_PATH = config.FACTS_FILE

# STRICT TAXONOMY
ALLOWED_CATEGORIES = [
    "name", "os", "location", "language",
    "dog", "favorite_anime", "job", "project", "user"
]

def load_facts():
    if not os.path.exists(FACTS_PATH):
        return {}
    try:
        with open(FACTS_PATH, "r") as f:
            return json.load(f)
    except:
        return {}

def save_facts(data):
    with open(FACTS_PATH, "w") as f:
        json.dump(data, f, indent=2)

def update_fact(category, value):
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
