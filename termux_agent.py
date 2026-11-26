#!/usr/bin/env python3
"""NoRestrictions Termux companion: locally approved workspace file writes only."""
import asyncio
from pathlib import Path
import httpx

BASE = "https://norestrictions-agent.sdrhaldwane.workers.dev"
DEVICE_ID = "huawei-termux-01"
ROOT = Path.home() / "norestrictions-agent"
WORKSPACE = ROOT / "workspace"
KEY_FILE = ROOT / ".agent_key"
ALLOWED = {".py", ".js", ".mjs", ".cjs", ".html", ".css", ".json", ".md", ".txt", ".toml", ".yaml", ".yml", ".xml", ".svg"}

def safe_target(relative: str) -> Path:
    p = Path(relative)
    if p.is_absolute() or not relative or any(x in ("", ".", "..") or x.startswith(".") for x in p.parts):
        raise ValueError("Invalid relative path")
    if p.suffix.lower() not in ALLOWED:
        raise ValueError("File extension is not allowed")
    target = (WORKSPACE / p).resolve()
    if WORKSPACE.resolve() not in target.parents:
        raise ValueError("Path escapes workspace")
    return target

async def main():
    if not KEY_FILE.is_file():
        raise SystemExit("Missing .agent_key. Do not share its contents.")
    token = KEY_FILE.read_text().strip()
    if len(token) < 32:
        raise SystemExit("Local device key is invalid.")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    print("NoRestrictions Agent connected. Workspace:", WORKSPACE)
    print("Only file-write tasks are supported. Each task requires local approval.")
    async with httpx.AsyncClient(timeout=25) as client:
        last_heartbeat = 0.0
        while True:
            try:
                loop_time = asyncio.get_running_loop().time()
                if loop_time - last_heartbeat >= 60:
                    r = await client.post(BASE + "/heartbeat", headers=headers)
                    r.raise_for_status()
                    last_heartbeat = loop_time
                    print("Heartbeat: online")
                r = await client.get(BASE + "/tasks/next", headers=headers)
                r.raise_for_status()
                task = r.json().get("task")
                if not task:
                    await asyncio.sleep(5)
                    continue
                task_id = task.get("id", "")
                try:
                    if task.get("kind") != "write_file":
                        raise ValueError("Unsupported task type")
                    target = safe_target(task.get("path", ""))
                    body = task.get("content", "")
                    if not isinstance(body, str) or len(body) > 24000:
                        raise ValueError("Content exceeds the allowed size")
                    print("\nIncoming file-write request")
                    print("Task:", task_id)
                    print("Target:", target.relative_to(WORKSPACE))
                    print("Characters:", len(body))
                    print("Preview:")
                    print("\n".join(body.splitlines()[:8])[:700])
                    answer = input("Approve this file write? [y/N]: ").strip().lower()
                    if answer not in ("y", "yes"):
                        status, result = "rejected", "Declined locally"
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(body, encoding="utf-8")
                        status, result = "completed", f"Wrote {target.relative_to(WORKSPACE)}"
                        print(result)
                except Exception as exc:
                    status, result = "failed", str(exc)[:300]
                    print("Task failed:", result)
                await client.post(BASE + "/tasks/complete",
                                  headers=headers,
                                  json={"id": task_id, "status": status, "result": result})
            except (httpx.HTTPError, ValueError) as exc:
                print("Connection/task error:", str(exc)[:200])
                await asyncio.sleep(8)
            except (KeyboardInterrupt, asyncio.CancelledError):
                break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAgent stopped.")
