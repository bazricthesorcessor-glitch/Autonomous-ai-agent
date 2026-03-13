import os
from enum import Enum, auto

class SystemState(Enum):
    IDLE = auto()
    PLANNING = auto()
    EXECUTING_TOOL = auto()
    WAITING_FOR_USER = auto()
    WAITING_FOR_SUDO = auto()
    ERROR = auto()

class TurnContext:
    """
    The shared state packet for a single user interaction.
    Passed through Brain -> Router -> Tools -> Brain.
    """
    MAX_RETRIES = 3

    def __init__(self, request):
        self.request = request
        self.cwd = os.getcwd()
        self.steps_taken = []
        self.last_result = None
        self.retry_count = 0
        self.state = SystemState.IDLE

    def add_step(self, decision, result):
        """Logs a step into history for context awareness."""
        summary = f"Action: {decision.get('decision')} | Tool: {decision.get('tool')} | Outcome: {str(result)[:50]}..."
        self.steps_taken.append(summary)
        self.last_result = str(result)
