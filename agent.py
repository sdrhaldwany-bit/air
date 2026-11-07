import os
import sys
import json
import time
import hashlib
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

VERSION = "8.0"
SERVER = os.environ.get(
    "NR_SERVER",
    "https://norestrictions-api.sdrhaldwane.workers.dev"
).rstrip("/")

WORKSPACE = Path.home() / "nr_workspace"
WORKSPACE.mkdir(exist_ok=True)

if len(sys.argv) > 1:
    KEY = sys.argv[1]
else:
    KEY = input("Device Key: ").strip()

if len(KEY) < 32:
    print("Invalid device key")
    sys.exit(1)


def request(method, endpoint, data=None):
    url = SERVER + endpoint
    body = json.dumps(data).encode() if data is not None else None

    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def safe_path(filename):
    path = (WORKSPACE / filename).resolve()

    if path != WORKSPACE and WORKSPACE not in path.parents:
        raise ValueError("Path outside workspace")

    return path


def execute_task(task):
    action = task.get("action")

    if action == "help":
        return "Supported: write_file, read_file, list_files, mkdir, run_python"

    if action == "write_file":
        path = safe_path(task["path"])
        content = task.get("content", "")

        if len(content) > 500_000:
            raise ValueError("File too large")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"File created: {path.name}"

    if action == "read_file":
        path = safe_path(task["path"])

        if not path.is_file():
            raise FileNotFoundError(path.name)

        if path.stat().st_size > 500_000:
            raise ValueError("File too large")

        return path.read_text(encoding="utf-8")

    if action == "list_files":
        folder = safe_path(task.get("path", "."))
        if not folder.is_dir():
            raise NotADirectoryError(folder.name)

        return "\n".join(
            str(p.relative_to(WORKSPACE))
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        )[:20000]

    if action == "mkdir":
        path = safe_path(task["path"])
        path.mkdir(parents=True, exist_ok=True)
        return f"Directory created: {path.name}"

    if action == "run_python":
        path = safe_path(task["path"])

        if not path.is_file() or path.suffix != ".py":
            raise ValueError("A Python file inside the workspace is required")

        result = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=30
        )

        return json.dumps({
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
            "exit_code": result.returncode
        }, ensure_ascii=False)

    raise ValueError("Unsupported action")


def send_result(job_id, output, exit_code):
    request("POST", "/api/device/done", {
        "key": KEY,
        "id": job_id,
        "output": str(output)[:20000],
        "exit_code": exit_code
    })


def main():
    print(f"NoRestrictions Agent {VERSION}")
    print("Workspace:", WORKSPACE)
    print("Connecting to server...")

    while True:
        try:
            data = request(
                "GET",
                "/api/device/poll?key=" + KEY
            )

            for job in data.get("jobs", []):
                job_id = job.get("id")

                try:
                    raw = job.get("command", "{}")
                    task = json.loads(raw) if isinstance(raw, str) else raw

                    print("\n[JOB]", job_id)
                    print("[ACTION]", task.get("action"))

                    output = execute_task(task)
                    send_result(job_id, output, 0)

                    print("[DONE]", job_id)

                except Exception as error:
                    send_result(job_id, str(error), 1)
                    print("[ERROR]", error)

        except KeyboardInterrupt:
            print("\nAgent stopped.")
            break

        except Exception as error:
            print("[CONNECTION ERROR]", error)

        time.sleep(3)


if __name__ == "__main__":
    main()
