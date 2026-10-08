"""Configure only the linked Lakshya project; never print credentials."""

import base64
import json
import secrets
from pathlib import Path

import requests

root = Path(__file__).resolve().parents[1]
project = json.loads((root / ".vercel/project.json").read_text())
auth = json.loads((Path.home() / ".local/share/com.vercel.cli/auth.json").read_text())
headers = {"Authorization": "Bearer " + auth["token"]}
base = "https://api.vercel.com"
params = {"teamId": project["orgId"]}
r = requests.patch(
    base + "/v9/projects/" + project["projectId"],
    params=params,
    headers=headers,
    json={
        "framework": "services",
        "rootDirectory": None,
        "buildCommand": None,
        "outputDirectory": None,
        "installCommand": None,
        "nodeVersion": "22.x",
    },
    timeout=30,
)
print("Project settings:", r.status_code)
if not r.ok:
    print(r.json().get("error", {}).get("code"))
    raise SystemExit(1)
path = root / "data/cloud-secrets.json"
if path.exists():
    values = json.loads(path.read_text())
else:
    values = {
        "LAKSHYA_SERVICE_KEY": secrets.token_urlsafe(48),
        "LAKSHYA_STORAGE_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "CRON_SECRET": secrets.token_urlsafe(48),
    }
    path.write_text(json.dumps(values))
    path.chmod(0o600)
r = requests.get(
    base + "/v10/projects/" + project["projectId"] + "/env",
    params=params,
    headers=headers,
    timeout=30,
)
r.raise_for_status()
existing = {x["key"] for x in r.json()["envs"]}
for name, value in values.items():
    if name not in existing:
        r = requests.post(
            base + "/v10/projects/" + project["projectId"] + "/env",
            params=params,
            headers=headers,
            json={"key": name, "value": value, "type": "encrypted", "target": ["production"]},
            timeout=30,
        )
        print(name, r.status_code)
        r.raise_for_status()
