"""Generate a private local access key without printing or overwriting credentials."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
content = path.read_text() if path.exists() else (root / ".env.example").read_text()
lines = content.splitlines()
values = dict(
    line.split("=", 1) for line in lines if line and not line.startswith("#") and "=" in line
)
key = values.get("LAKSHYA_API_KEY", "")
if len(key) < 32 or key == "local-demo-key-change-me":
    key = secrets.token_urlsafe(48)
    lines = [line for line in lines if not line.startswith("LAKSHYA_API_KEY=")]
    lines.append("LAKSHYA_API_KEY=" + key)
for name, value in {"GEMINI_API_KEY": "", "LAKSHYA_AI_PROVIDER": ""}.items():
    if name not in values:
        lines.append(name + "=" + value)
descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w") as stream:
    stream.write("\n".join(lines) + "\n")
path.chmod(0o600)
print(f"Private dashboard key ready in {path}. Provider credentials preserved.")
