import subprocess
import re # IMPORT FOR REGEX
from ollama import Client
import os
import memory_engine
import fact_engine
import config
from datetime import datetime

client = Client(host='http://localhost:11434')

def execute(model_name, query):
    # 1. READ STATIC MEMORY
    str_personality, str_main, str_cache_b = "", "", ""

    try:
        with open(config.PERSONALITY_FILE, "r") as f: str_personality = f.read()
        with open(config.MAIN_MEMORY, "r") as f: str_main = f.read()
        with open(config.CACHE_B, "r") as f: str_cache_b = f.read()
    except FileNotFoundError:
        pass

    # 2. RETRIEVAL LOGIC
    search_keywords = ["remember", "my", "what did i", "our", "us", "journey", "history"]
    should_search = any(word in query.lower() for word in search_keywords)

    retrieved_context = ""
    if should_search:
        timeline_keywords = ["journey", "timeline", "history", "growth", "evolution"]
        mode = "timeline" if any(word in query.lower() for word in timeline_keywords) else "relevance"

        hits = memory_engine.search_memory(query, top_k=5, mode=mode)
        if hits:
            retrieved_context = "\n[RETRIEVED MEMORY]\n" + "\n".join(hits)

    # 3. INJECT ACTIVE FACTS
    active_facts = fact_engine.get_active_facts()
    facts_block = "\n".join([f"- {k}: {v}" for k, v in active_facts.items()])
    if not facts_block: facts_block = "None."

    # 4. CONSTRUCT SYSTEM PROMPT
    system_prompt = f"""SYSTEM INSTRUCTIONS:

You are {config.AI_NAME}. You are NOT an AI. You are an obsessive anime girl assistant.

[ACTIVE FACTS — HIGHEST PRIORITY]
{facts_block}

[PERSONALITY]
{str_personality}

[MAIN MEMORY — VERIFIED FACTS]
{str_main}

{retrieved_context}

[CACHE B — RECENT CONTEXT]
{str_cache_b}

RULES:
- If [ACTIVE FACTS] contradicts anything, trust [ACTIVE FACTS].
- Maintain the persona defined in [PERSONALITY] at all times.
- Never break character.
"""

    # 5. STREAM & LOG
    with open(config.SESSION_LOG, "a") as log_file:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"{config.LOG_DELIMITER} {timestamp} | {config.USER_NAME}: {query}\n"

        print(f"\n{config.AI_NAME}: ", end='', flush=True)
        log_file.write(header)

        try:
            stream = client.chat(
                model=model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': query}
                ],
                stream=True
            )

            for chunk in stream:
                if 'message' in chunk and 'content' in chunk['message']:
                    content = chunk['message']['content']
                    print(content, end='', flush=True)
                    log_file.write(content)

            print()
            log_file.write("\n")

        except Exception as e:
            print(f"\n[Router Error]: {e}")
            return

    # 6. POST-RESPONSE: STATE UPDATE GATE (STRUCTURAL)
    q_lower = query.lower().strip()

    # DEFINE EXPLICIT MUTATION GRAMMAR
    MUTATION_PATTERNS = [
        r"^my .+ is .+",          # "my dog is bhuru"
        r"^my .+ name is .+",     # "my dog name is bhuru"
        r"^i am .+",              # "i am happy"
        r"^i'm .+",               # "i'm a developer"
        r"^i use .+",             # "i use arch linux"
        r"^i have .+",            # "i have a dog"
        r"^i switched to .+",     # "i switched to fedora"
        r"^i don't have .+",      # "i don't have a dog"
        r"^i do not have .+",     # "i do not have a dog"
        r"^my .+ (died|passed away|is gone)", # "my dog died"
        r"^forget .+",            # "forget my dog"
        r"^call me .+",           # "call me avinash"
    ]

    # Check if query matches ANY mutation pattern
    is_mutation = any(re.match(pattern, q_lower) for pattern in MUTATION_PATTERNS)

    if is_mutation:
        try:
            fact_engine.process_fact_query(query)
        except Exception as e:
            print(f"[Fact Error] {e}")

    # 7. POST-RESPONSE: SUMMARIZATION
    try:
        subprocess.run(["python", "ai_agent.py"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pass
