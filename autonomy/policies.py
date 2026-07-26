import logging

logger = logging.getLogger("aria")

class PolicyEngine:
    def __init__(self):
        # Autonomous behavioral safety rules
        self.rules = {
            "delete_files": "deny",
            "send_emails": "confirm",
            "max_retries": 3,
            "stop_on_consecutive_failures": 3
        }

    def evaluate_action_policy(self, action_name: str) -> str:
        if action_name in ["file_delete", "drop_database"]:
            return self.rules.get("delete_files", "deny")
        if action_name in ["email_send", "message_dispatch"]:
            return self.rules.get("send_emails", "confirm")
        return "allow"
