import os
import re
import sys
import subprocess

SECRET_PATTERN = re.compile(r"""(token|key|secret|api_key|bot[0-9]+:)\s*=\s*['\"][^'\"]{8,}""", re.I)
BANNED_WORDS = [
    "Exciting", "Buckle up", "Get ready", "Let's dive in", "Unleash",
    "Elevate", "Seamless", "Game-changer", "Thrilling", "Electrifying",
    "What a moment!", "Stay tuned"
]

def run_checks():
    errors = []
    # 1. Check git tracking of .env
    try:
        tracked = subprocess.check_output(["git", "ls-files", ".env"], text=True).strip()
        if tracked:
            errors.append("CRITICAL: .env is tracked by git!")
    except Exception:
        pass

    # 2. Check for secrets
    for root, dirs, files in os.walk("."):
        if ".venv" in root or "__pycache__" in root or ".git" in root:
            continue
        for file in files:
            if not file.endswith((".py", ".yaml", ".json", ".md")):
                continue
            if file in ("rules.md", ".env.example", "check_rules.py"):
                continue
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f, 1):
                    if SECRET_PATTERN.search(line):
                        if "your-" in line or "<" in line:
                            continue
                        errors.append(f"Secret pattern matched in {path}:{idx}: {line.strip()}")

    if errors:
        for err in errors:
            print("FAILED:", err)
        sys.exit(1)
    else:
        print("Self-check passed: 0 secret violations, .env safe.")

if __name__ == "__main__":
    run_checks()
