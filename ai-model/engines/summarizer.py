# ========================= engines/summarizer.py =========================
import os
from datetime import datetime
from ollama import Client
import config

client = Client(host='http://localhost:11434')

# Approximate character limit to stay within LLM context window
_MAX_LOG_CHARS = 12000


def generate_summary(raw_log_path):
    if not os.path.exists(raw_log_path): return None
    with open(raw_log_path, "r") as f: content = f.read()
    if not content.strip(): return "Empty log."

    # Truncate to avoid blowing context; keep tail (most recent messages)
    if len(content) > _MAX_LOG_CHARS:
        content = "... [truncated older messages] ...\n" + content[-_MAX_LOG_CHARS:]

    prompt = f"""
Summarize this conversation log into a structured format.
Focus on key information, decisions, and technical details.

LOG:
{content}

OUTPUT FORMAT:
Topics: [List key topics discussed]
Decisions Made: [List any decisions]
Technical Changes: [List code, commands, or errors]
Unresolved Issues: [List open questions]
Important User States: [Mood, preferences, location changes]
"""
    try:
        response = client.chat(model=config.CHAT_MODEL, messages=[{'role': 'user', 'content': prompt}], options={'temperature': 0.1})
        return response['message']['content']
    except Exception as e:
        print(f"Summarization error: {e}")
        return "Summary generation failed."

def run_summarization():
    print("Running Daily Summarization...")
    if not os.path.exists(config.DAILY_DIR): return

    today = datetime.now().date()
    folders = sorted([f for f in os.listdir(config.DAILY_DIR) if os.path.isdir(os.path.join(config.DAILY_DIR, f))])

    for folder in folders:
        try:
            folder_date = datetime.strptime(folder, "%Y-%m-%d").date()
            age_days = (today - folder_date).days

            raw_path = os.path.join(config.DAILY_DIR, folder, "raw.log")
            summary_path = os.path.join(config.DAILY_DIR, folder, "summary.txt")

            # Generate summaries for days 3+ (was > 10, caused 8-day blackout)
            if os.path.exists(raw_path) and not os.path.exists(summary_path):
                if age_days >= 3:
                    print(f"Summarizing {folder} (Day {age_days})...")
                    summary_text = generate_summary(raw_path)
                    with open(summary_path, "w") as f:
                        f.write(summary_text)
                    print(f"Created summary for {folder}")
                    # Only delete raw log once past the retention window
                    if age_days > config.RAW_DAYS_WINDOW:
                        try:
                            os.remove(raw_path)
                            print(f"Cleaned up raw log for {folder}")
                        except OSError as rm_err:
                            print(f"[Summarizer] Could not remove {raw_path}: {rm_err}")
        except ValueError:
            continue

if __name__ == "__main__":
    run_summarization()
