# ========================= tools/utilities.py =========================
"""
Utility tools pack — instant, no-LLM tools.

Usage (from brain/router):
    run_tool({"action": "flip_coin"})
    run_tool({"action": "roll_dice", "sides": 6, "count": 2})
    run_tool({"action": "time_now"})
    run_tool({"action": "date_today"})
    run_tool({"action": "count_words", "text": "Hello world"})
    run_tool({"action": "convert_units", "value": 100, "from": "celsius", "to": "fahrenheit"})
    run_tool({"action": "generate_password", "length": 20, "symbols": true})
    run_tool({"action": "uuid_generate"})
    run_tool({"action": "random_number", "min": 1, "max": 100})
    run_tool({"action": "random_quote"})
    run_tool({"action": "list"})
"""

import random
import string
import uuid
import math
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    action = str(args.get("action", "")).strip().lower()

    _map = {
        "flip_coin":        _flip_coin,
        "roll_dice":        _roll_dice,
        "time_now":         _time_now,
        "date_today":       _date_today,
        "count_words":      _count_words,
        "convert_units":    _convert_units,
        "generate_password": _generate_password,
        "uuid_generate":    _uuid_generate,
        "random_number":    _random_number,
        "random_quote":     _random_quote,
        "list":             _list_actions,
    }

    if not action:
        return "[Utilities] No action specified. Call with action='list' so see available tools."

    fn = _map.get(action)
    if fn is None:
        return f"[Utilities] Unknown action '{action}'. Available: {', '.join(_map.keys())}"

    try:
        return fn(args)
    except Exception as e:
        return f"[Utilities] Error in '{action}': {e}"


# ---------------------------------------------------------------------------
# Individual tools
# ---------------------------------------------------------------------------

def _flip_coin(args: dict) -> str:
    result = random.choice(["Heads", "Tails"])
    return f"Coin flip: **{result}**"


def _roll_dice(args: dict) -> str:
    sides = max(2, int(args.get("sides", 6)))
    count = max(1, min(int(args.get("count", 1)), 20))  # cap at 20 dice
    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls)
    if count == 1:
        return f"Rolled d{sides}: **{rolls[0]}**"
    rolls_str = ", ".join(str(r) for r in rolls)
    return f"Rolled {count}d{sides}: [{rolls_str}] — Total: **{total}**"


def _time_now(args: dict) -> str:
    now = datetime.now()
    utc  = datetime.now(timezone.utc)
    return (
        f"Local time : {now.strftime('%H:%M:%S')}  ({now.strftime('%Z') or 'local'})\n"
        f"UTC time   : {utc.strftime('%H:%M:%S')} UTC\n"
        f"Unix epoch : {int(utc.timestamp())}"
    )


def _date_today(args: dict) -> str:
    today = datetime.now()
    day_name  = today.strftime("%A")
    date_str  = today.strftime("%d %B %Y")
    week_num  = today.strftime("%W")
    day_of_yr = today.timetuple().tm_yday
    return (
        f"Today: **{day_name}, {date_str}**\n"
        f"Week: {week_num}  |  Day of year: {day_of_yr}\n"
        f"ISO: {today.strftime('%Y-%m-%d')}"
    )


def _count_words(args: dict) -> str:
    text = str(args.get("text", ""))
    if not text:
        return "[count_words] No 'text' provided."
    words = len(text.split())
    chars = len(text)
    chars_no_space = len(text.replace(" ", ""))
    lines = text.count("\n") + 1
    sentences = text.count(".") + text.count("!") + text.count("?")
    return (
        f"Words: {words}\n"
        f"Characters: {chars}  (without spaces: {chars_no_space})\n"
        f"Lines: {lines}\n"
        f"Sentences (approx): {sentences}"
    )


# --- Unit conversion tables ------------------------------------------------

_UNIT_CATEGORIES = {
    # ---------- Temperature ----------
    "celsius":    ("temp", 1.0),
    "fahrenheit": ("temp", 1.0),
    "kelvin":     ("temp", 1.0),
    # ---------- Length (base = meters) ----------
    "meters":      ("length", 1.0),
    "meter":       ("length", 1.0),
    "km":          ("length", 1000.0),
    "kilometers":  ("length", 1000.0),
    "km":          ("length", 1000.0),
    "cm":          ("length", 0.01),
    "centimeters": ("length", 0.01),
    "mm":          ("length", 0.001),
    "millimeters": ("length", 0.001),
    "miles":       ("length", 1609.344),
    "mile":        ("length", 1609.344),
    "feet":        ("length", 0.3048),
    "foot":        ("length", 0.3048),
    "ft":          ("length", 0.3048),
    "inches":      ("length", 0.0254),
    "inch":        ("length", 0.0254),
    "in":          ("length", 0.0254),
    "yards":       ("length", 0.9144),
    "yard":        ("length", 0.9144),
    "yd":          ("length", 0.9144),
    # ---------- Weight (base = kilograms) ----------
    "kg":          ("weight", 1.0),
    "kilograms":   ("weight", 1.0),
    "grams":       ("weight", 0.001),
    "gram":        ("weight", 0.001),
    "g":           ("weight", 0.001),
    "mg":          ("weight", 0.000001),
    "milligrams":  ("weight", 0.000001),
    "pounds":      ("weight", 0.453592),
    "pound":       ("weight", 0.453592),
    "lbs":         ("weight", 0.453592),
    "lb":          ("weight", 0.453592),
    "ounces":      ("weight", 0.0283495),
    "ounce":       ("weight", 0.0283495),
    "oz":          ("weight", 0.0283495),
    "tonnes":      ("weight", 1000.0),
    "tonne":       ("weight", 1000.0),
    "ton":         ("weight", 907.185),   # US short ton
    # ---------- Data (base = bytes) ----------
    "bytes":       ("data", 1),
    "byte":        ("data", 1),
    "b":           ("data", 1),
    "kb":          ("data", 1024),
    "kilobytes":   ("data", 1024),
    "mb":          ("data", 1024**2),
    "megabytes":   ("data", 1024**2),
    "gb":          ("data", 1024**3),
    "gigabytes":   ("data", 1024**3),
    "tb":          ("data", 1024**4),
    "terabytes":   ("data", 1024**4),
    # ---------- Speed (base = m/s) ----------
    "m/s":         ("speed", 1.0),
    "mps":         ("speed", 1.0),
    "km/h":        ("speed", 1/3.6),
    "kmh":         ("speed", 1/3.6),
    "kph":         ("speed", 1/3.6),
    "mph":         ("speed", 0.44704),
    "knots":       ("speed", 0.514444),
    "knot":        ("speed", 0.514444),
}

def _convert_units(args: dict) -> str:
    try:
        value = float(args.get("value", 0))
    except (TypeError, ValueError):
        return "[convert_units] 'value' must be a number."

    from_unit = str(args.get("from", "")).strip().lower()
    to_unit   = str(args.get("to", "")).strip().lower()

    if not from_unit or not to_unit:
        return "[convert_units] Provide 'from' and 'to' unit names."

    if from_unit not in _UNIT_CATEGORIES:
        return f"[convert_units] Unknown unit: '{from_unit}'."
    if to_unit not in _UNIT_CATEGORIES:
        return f"[convert_units] Unknown unit: '{to_unit}'."

    from_cat, from_factor = _UNIT_CATEGORIES[from_unit]
    to_cat,   to_factor   = _UNIT_CATEGORIES[to_unit]

    if from_cat != to_cat:
        return f"[convert_units] Cannot convert {from_cat} to {to_cat}."

    # Temperature needs special handling
    if from_cat == "temp":
        result = _convert_temperature(value, from_unit, to_unit)
        if result is None:
            return f"[convert_units] Unsupported temperature pair: {from_unit} → {to_unit}."
    else:
        # Convert via base unit
        base_value = value * from_factor
        result = base_value / to_factor

    # Format nicely
    if abs(result) >= 1e6 or (abs(result) < 0.001 and result != 0):
        result_str = f"{result:.6e}"
    elif result == int(result):
        result_str = f"{int(result)}"
    else:
        result_str = f"{result:.6g}"

    return f"{value} {from_unit} = **{result_str} {to_unit}**"


def _convert_temperature(value: float, fr: str, to: str):
    if fr == to:
        return value
    # to Celsius first
    if fr == "celsius":
        c = value
    elif fr == "fahrenheit":
        c = (value - 32) * 5/9
    elif fr == "kelvin":
        c = value - 273.15
    else:
        return None
    # Celsius to target
    if to == "celsius":
        return c
    elif to == "fahrenheit":
        return c * 9/5 + 32
    elif to == "kelvin":
        return c + 273.15
    return None


def _generate_password(args: dict) -> str:
    length  = max(8, min(int(args.get("length", 16)), 128))
    use_sym = str(args.get("symbols", "true")).lower() not in ("false", "0", "no")
    use_num = str(args.get("numbers", "true")).lower() not in ("false", "0", "no")

    pool = string.ascii_letters
    if use_num:
        pool += string.digits
    if use_sym:
        pool += "!@#$%^&*()-_=+[]{}|;:,.<>?"

    # Guarantee at least one of each requested type
    parts = [random.choice(string.ascii_uppercase),
             random.choice(string.ascii_lowercase)]
    if use_num:
        parts.append(random.choice(string.digits))
    if use_sym:
        parts.append(random.choice("!@#$%^&*()-_=+"))

    remaining = length - len(parts)
    parts += [random.choice(pool) for _ in range(remaining)]
    random.shuffle(parts)
    password = "".join(parts)

    return (
        f"Generated password ({length} chars):\n"
        f"`{password}`\n"
        f"Strength: {'Strong' if length >= 16 and use_sym and use_num else 'Medium' if length >= 12 else 'Basic'}"
    )


def _uuid_generate(args: dict) -> str:
    version = int(args.get("version", 4))
    if version == 1:
        result = str(uuid.uuid1())
    elif version == 4:
        result = str(uuid.uuid4())
    else:
        result = str(uuid.uuid4())
        version = 4
    return f"UUID v{version}: `{result}`"


def _random_number(args: dict) -> str:
    try:
        low  = float(args.get("min", 1))
        high = float(args.get("max", 100))
    except (TypeError, ValueError):
        return "[random_number] 'min' and 'max' must be numbers."

    if low >= high:
        return "[random_number] 'min' must be less than 'max'."

    # Integer if both are integers
    if low == int(low) and high == int(high):
        result = random.randint(int(low), int(high))
        return f"Random number between {int(low)} and {int(high)}: **{result}**"
    else:
        result = round(random.uniform(low, high), 6)
        return f"Random number between {low} and {high}: **{result}**"


_QUOTES = [
    ("The best way to predict the future is to create it.", "Abraham Lincoln"),
    ("It does not matter how slowly you go as long as you do not stop.", "Confucius"),
    ("An unexamined life is not worth living.", "Socrates"),
    ("Simplicity is the ultimate sophistication.", "Leonardo da Vinci"),
    ("In the middle of every difficulty lies opportunity.", "Albert Einstein"),
    ("The only way to do great work is to love what you do.", "Steve Jobs"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Code is like humor. When you have to explain it, it's bad.", "Cory House"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("Programs must be written for people to read, and only incidentally for machines to execute.", "Harold Abelson"),
    ("The function of good software is to make the complex appear simple.", "Grady Booch"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("Premature optimization is the root of all evil.", "Donald Knuth"),
    ("Every great developer you know got there by solving problems they were unqualified to solve.", "Patrick McKenzie"),
    ("The most disastrous thing that you can ever learn is your first programming language.", "Alan Kay"),
    ("Strive not to be a success, but rather to be of value.", "Albert Einstein"),
    ("Your time is limited, so don't waste it living someone else's life.", "Steve Jobs"),
    ("The impediment to action advances action. What stands in the way becomes the way.", "Marcus Aurelius"),
    ("You have power over your mind — not outside events. Realize this, and you will find strength.", "Marcus Aurelius"),
    ("He who fights with monsters should be careful lest he thereby become a monster.", "Friedrich Nietzsche"),
]

def _random_quote(args: dict) -> str:
    text, author = random.choice(_QUOTES)
    return f'"{text}"\n\n— *{author}*'


def _list_actions(args: dict) -> str:
    return (
        "Available utility actions:\n"
        "  flip_coin          — Flip a coin (Heads/Tails)\n"
        "  roll_dice          — Roll dice [sides=6, count=1]\n"
        "  time_now           — Current local + UTC time\n"
        "  date_today         — Today's date with week/day info\n"
        "  count_words        — Word/char/line count [text=...]\n"
        "  convert_units      — Unit conversion [value, from, to]\n"
        "  generate_password  — Secure password [length=16, symbols=true, numbers=true]\n"
        "  uuid_generate      — Generate UUID [version=4]\n"
        "  random_number      — Random number in range [min=1, max=100]\n"
        "  random_quote       — Inspiring quote"
    )
