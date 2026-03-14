import psutil
import platform
import shutil

def run_tool(args):
    """
    Gathers system diagnostics (CPU, RAM, Disk).
    Returns a formatted string summary.
    """
    try:
        # CPU
        cpu_load = psutil.cpu_percent(interval=0.1)

        # RAM
        mem = psutil.virtual_memory()
        ram_total = f"{mem.total / (1024**3):.2f} GB"
        ram_used = f"{mem.used / (1024**3):.2f} GB"
        ram_percent = mem.percent

        # Disk (Root partition)
        disk = psutil.disk_usage('/')
        disk_total = f"{disk.total / (1024**3):.2f} GB"
        disk_used = f"{disk.used / (1024**3):.2f} GB"
        disk_percent = disk.percent

        result = (
            "--- SYSTEM DIAGNOSTICS ---\n"
            f"OS: {platform.system()} {platform.release()}\n"
            f"CPU Load: {cpu_load}%\n"
            f"RAM: {ram_used} / {ram_total} ({ram_percent}%)\n"
            f"Disk: {disk_used} / {disk_total} ({disk_percent}%)\n"
        )
        return result

    except Exception as e:
        return f"Error gathering diagnostics: {str(e)}"
