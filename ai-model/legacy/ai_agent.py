from ollama import Client
import config

client = Client(host='http://localhost:11434')

def run_agent():
    try:
        with open(config.SESSION_LOG, "r") as f:
            chat_log = f.read()
    except FileNotFoundError:
        return

    if not chat_log.strip(): return

    prompt = f"""You are a summarizer.
Summarize the following chat log into a short paragraph of facts.
Ignore idle chatter.

LOG:
{chat_log}

SUMMARY:
"""

    try:
        response = client.chat(
            model=config.CHAT_MODEL,
            messages=[{'role': 'user', 'content': prompt}]
        )
        summary = response['message']['content']

        with open(config.CACHE_B, "w") as f:
            f.write(summary)

    except Exception as e:
        print(f"[Agent Error] {e}")

if __name__ == "__main__":
    run_agent()
