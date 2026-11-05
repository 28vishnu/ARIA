import subprocess
import re
import logging

# Commands requiring explicit Telegram admin approval
HIGH_RISK_PATTERNS = [
    r"rm\s+-rf", r"Remove-Item.*-Recurse", r"Format-Volume", 
    r"Stop-Computer", r"Restart-Computer", r"Set-ExecutionPolicy",
    r"git\s+reset\s+--hard", r"drop\s+database"
]

class SecurityExecutor:
    def __init__(self, admin_chat_id: int):
        self.admin_chat_id = admin_chat_id

    def is_high_risk(self, command: str) -> bool:
        for pattern in HIGH_RISK_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    def execute_powershell(self, command: str) -> dict:
        """Executes a PowerShell command locally and captures output."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True,
                text=True,
                timeout=60
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "stdout": "", "stderr": "Command execution timed out (60s)."}
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e)}
