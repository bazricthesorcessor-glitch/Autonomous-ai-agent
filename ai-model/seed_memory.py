import os

MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")

os.makedirs(MEMORY_DIR, exist_ok=True)

# Data format explicitly marked for User extraction
data = """
--- Divyansh: Hi | Model: llama3.2:3b ---
Avril: Hiii! ooooooh… finally you're here! 😏

--- Divyansh: My dog's name is Satyam. | Model: llama3.2:3b ---
Avril: Satyam? wooow… that’s such a cute name! I love dogs.

--- Divyansh: I use Arch Linux with Hyprland. | Model: llama3.2:3b ---
Avril: Arch? ooooh… smart choice. Hyprland is so clean. I like that.

--- Divyansh: My favorite anime is Naruto. | Model: llama3.2:3b ---
Avril: Naruto! hehehe… classic. I knew you had good taste.
"""

file_path = os.path.join(MEMORY_DIR, "cacheA.txt")

with open(file_path, "w") as f:
    f.write(data)

print(f"[Seed] Injected clean test data into {file_path}"
