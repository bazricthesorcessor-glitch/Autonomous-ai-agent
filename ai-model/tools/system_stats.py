import psutil
import shutil
import platform

def run_tool():
    """
    Gathers system diagnostics.
    Returns a formatted string.
    """
    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)

        # RAM
        mem = psutil.virtual_memory()
        ram_total = f"{mem.total / (1024**3):.2f} GB"
        ram_used = f"{mem.used / (1024**3):.2f} GB"
        ram_percent = mem.percent

        # Disk
        disk = psutil.disk_usage('/')
        disk_total = f"{disk.total / (1024**3):.2f} GB"
        disk_used = f"{disk.used / (1024**3):.2f} GB"
        disk_percent = disk.percent

        result = (
            f"--- SYSTEM DIAGNOSTICS ---\n"
            f"OS: {platform.system()} {platform.release()}\n"
            f"CPU Load: {cpu_percent}%\n"
            f"RAM: {ram_used} / {ram_total} ({ram_percent}%)\n"
            f"Disk: {disk_used} / {disk_total} ({disk_percent}%)\n"
        )
        return result

    except Exception as e:
        return f"Error getting stats: {e}"

# If run directly (for testing)
if __name__ == "__main__":
    print(run_tool())
