import os

class _FileToolInternal:
    """
    The actual logic class.
    """
    def __init__(self):
        self.allowed_root = os.path.expanduser("~")

    def list_files(self, path="."):
        try:
            target_path = os.path.abspath(os.path.join(self.allowed_root, path))

            # Security Check: Prevent escaping sandbox
            if not target_path.startswith(self.allowed_root):
                return "Error: Access Denied. Stay inside home directory."

            if not os.path.exists(target_path):
                return "Error: Path does not exist."

            items = os.listdir(target_path)
            annotated = []
            for item in items[:50]:
                full = os.path.join(target_path, item)
                kind = "DIR" if os.path.isdir(full) else "FILE"
                annotated.append(f"[{kind}] {item}")

            return "\n".join(annotated)
        except Exception as e:
            return f"Error listing files: {str(e)}"

    def read_file(self, path):
        try:
            target_path = os.path.abspath(os.path.join(self.allowed_root, path))

            if not target_path.startswith(self.allowed_root):
                return "Error: Access Denied."

            # Size Check (50KB limit)
            if os.path.getsize(target_path) > 1024 * 50:
                return "Error: File too large to read into context."

            with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {str(e)}"

# Initialize the internal instance
_tool_instance = _FileToolInternal()

def run_tool(args):
    """
    Adapter function for the Router.
    Matches the signature: def run_tool(args=None) -> str
    """
    if args is None:
        args = {}

    # Logic to decide which internal method to call
    action = args.get("action")

    if action == "list":
        return _tool_instance.list_files(args.get("path", "."))

    elif action == "read":
        filename = args.get("filename")
        if not filename:
            return "Error: No filename provided."
        return _tool_instance.read_file(filename)

    else:
        return "Error: Unknown action for file tool. Use 'list' or 'read'."
