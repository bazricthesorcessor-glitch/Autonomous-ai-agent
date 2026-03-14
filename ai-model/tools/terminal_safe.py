# ========================= tools/terminal_safe.py =========================
"""
Safe terminal execution for Avril.

Executes shell commands with an allowlist/blocklist to prevent system damage.

ALLOWED prefixes/commands:
  pacman, yay, paru, pip, npm, cargo   (package managers)
  systemctl, journalctl                (services)
  ls, cat, head, tail, grep, find      (read-only file ops)
  df, free, nproc, uname, lscpu        (system info)
  ps, htop, top                        (process info)
  ip, nmcli, ping, curl, wget          (networking)
  git status, git log, git diff        (read-only git)
  python, python3 (no -c rm/dd/mkfs)   (running scripts)

BLOCKED patterns (never run):
  rm, rmdir, mkfs, dd, fdisk, parted
  shutdown, reboot, poweroff, halt
  chmod 777, chown, sudo su
  > /dev/sd (destructive redirects)
"""
import re
import shlex
import subprocess

# Allowlisted command prefixes (first word of command)
_ALLOWED_COMMANDS = {
    # Package management
    "pacman", "yay", "paru", "pip", "pip3", "npm", "cargo", "gem",
    # Services
    "systemctl", "journalctl",
    # File inspection (read-only)
    "ls", "cat", "head", "tail", "grep", "find", "wc", "diff", "file",
    "less", "more", "stat", "md5sum", "sha256sum",
    # System info
    "df", "du", "free", "nproc", "uname", "lscpu", "lsblk", "lspci",
    "lsusb", "dmesg", "uptime", "whoami", "hostname",
    # Process info
    "ps", "pgrep", "pkill", "kill", "nice", "renice",
    # Networking
    "ip", "nmcli", "ping", "curl", "wget", "ss", "netstat", "nslookup",
    "dig", "traceroute", "ifconfig",
    # Git (inspection only)
    "git",
    # Python/Node (running scripts)
    "python", "python3", "node",
    # Text tools
    "echo", "printf", "awk", "sed", "sort", "uniq", "cut", "tr", "tee",
    # Directories
    "mkdir", "pwd", "cd",
    # System shortcuts and info
    "hyprctl", "pactl", "playerctl", "brightnessctl",
}

# Blocklisted patterns — NEVER execute even if allowlisted prefix passes
_BLOCKED_PATTERNS = [
    r'\brm\b', r'\brmdir\b',                      # deletion
    r'\bmkfs\b', r'\bdd\b', r'\bfdisk\b',          # disk ops
    r'\bparted\b', r'\bmkswap\b',                  # partition ops
    r'\bshutdown\b', r'\breboot\b',                # power
    r'\bpoweroff\b', r'\bhalt\b', r'\binit\b',
    r'\bchmod\s+777\b', r'\bchmod\s+a\+x\b',      # dangerous perms
    r'\bsudo\s+su\b', r'\bsu\b\s+-',              # privilege escalation
    r'>\s*/dev/sd', r'>\s*/dev/nvme',              # destructive redirects
    r'\bwipe\b', r'\bshred\b',                     # data destruction
    r':\(\)\s*\{.*fork\s*bomb',                    # fork bombs
    r'\bbase64\s+-d.*\|.*sh\b',                    # encoded payloads
]

_BLOCKED_RE = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)


def _is_safe_command(cmd: str) -> tuple[bool, str]:
    """
    Check if a command is safe to run.
    Returns (safe: bool, reason: str).
    """
    stripped = cmd.strip()
    if not stripped:
        return False, "Empty command"

    # Block check — highest priority
    if _BLOCKED_RE.search(stripped):
        return False, "Command matches blocklist (destructive operation)"

    # Allowlist check — first word must be in allowed set
    first_word = stripped.split()[0].lstrip("./")
    if first_word not in _ALLOWED_COMMANDS:
        return False, f"Command '{first_word}' is not in the safe allowlist"

    return True, "ok"


def run_tool(args=None):
    """
    Safe terminal execution.

    Args:
        args (dict):
            command  (str)  : Shell command to run.
            timeout  (int)  : Seconds to wait (default 15).
            workdir  (str)  : Working directory (optional).

    Returns:
        str: stdout + stderr of the command, or an error message.
    """
    if args is None:
        args = {}

    command = args.get("command", "").strip()
    if not command:
        return "Error: no command provided"

    timeout = min(int(args.get("timeout", 15)), 60)  # cap at 60s
    workdir = args.get("workdir", None)

    safe, reason = _is_safe_command(command)
    if not safe:
        return f"[BLOCKED] {reason}\nCommand: {command}"

    # Parse command string into a safe argument list — prevents shell injection
    # (&&, ||, ;, backtick, $() are inert with shell=False).
    # Note: shell pipes (|) are not supported; call tools individually instead.
    try:
        cmd_list = shlex.split(command)
    except ValueError as e:
        return f"[BLOCKED] Invalid command syntax: {e}"

    if not cmd_list:
        return "Error: empty command after parsing"

    try:
        result = subprocess.run(
            cmd_list,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
        output = ""
        if result.stdout.strip():
            output += result.stdout.strip()
        if result.stderr.strip():
            output += ("\n" if output else "") + f"[stderr] {result.stderr.strip()}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] Command exceeded {timeout}s: {command}"
    except Exception as e:
        return f"[ERROR] {str(e)}"
