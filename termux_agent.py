#!/usr/bin/env python3
"""NoRestrictions Termux companion: bounded workspace and device-info tasks."""
import argparse
import asyncio
import json
import platform
import secrets
import shutil
from pathlib import Path
import httpx

BASE = "https://norestrictions-agent.sdrhaldwane.workers.dev"
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

def device_info() -> str:
    usage = shutil.disk_usage(str(Path.home()))
    return json.dumps({
        "platform": platform.platform(), "system": platform.system(),
        "machine": platform.machine(), "python": platform.python_version(),
        "home": str(Path.home()), "workspace": str(WORKSPACE),
        "disk_total_bytes": usage.total, "disk_free_bytes": usage.free,
    }, ensure_ascii=False)

def list_files(relative: str = "") -> str:
    base = WORKSPACE.resolve()
    folder = base if not relative else safe_target(relative).parent if Path(relative).suffix else (base / relative).resolve()
    if base != folder and base not in folder.parents:
        raise ValueError("Path escapes workspace")
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Directory not found")
    items = []
    for p in sorted(folder.rglob("*")):
        if len(items) >= 200:
            break
        if p.is_file() and base in p.resolve().parents and not any(part.startswith(".") for part in p.relative_to(base).parts):
            items.append({"path": p.relative_to(base).as_posix(), "bytes": p.stat().st_size})
    return json.dumps(items, ensure_ascii=False)

def handle_task(task):
    kind = task.get("kind")
    if kind == "device_info":
        return device_info()
    if kind == "list_files":
        return list_files(str(task.get("path", "")))
    if kind == "read_file":
        target = safe_target(task.get("path", ""))
        if not target.is_file():
            raise ValueError("File not found")
        if target.stat().st_size > 24000:
            raise ValueError("File exceeds the 24 KB read limit")
        return target.read_text(encoding="utf-8")[:24000]
    if kind == "write_file":
        target = safe_target(task.get("path", ""))
        body = task.get("content", "")
        if not isinstance(body, str) or len(body) > 24000:
            raise ValueError("Content exceeds the allowed size")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return f"Wrote {target.relative_to(WORKSPACE)}"
    raise ValueError("Unsupported task type")

async def main():
    parser = argparse.ArgumentParser(description="NoRestrictions Termux Agent")
    parser.add_argument("--pair-code", help="One-time code from the owner pairing panel")
    parser.add_argument("--device-id", help="Device ID supplied by the pairing panel")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    if args.pair_code:
        if not args.device_id or len(args.pair_code) > 32:
            raise SystemExit("Pairing code and device ID are required.")
        new_token = secrets.token_hex(32)
        async with httpx.AsyncClient(timeout=20) as pairing_client:
            response = await pairing_client.post(BASE + "/pair", json={
                "code": args.pair_code, "device_id": args.device_id, "device_token": new_token
            })
            if response.status_code != 200:
                try:
                    detail = response.json().get("error", "pair_failed")
                except Exception:
                    detail = "pair_failed"
                raise SystemExit("Pairing failed: " + str(detail))
        KEY_FILE.write_text(new_token, encoding="utf-8")
        KEY_FILE.chmod(0o600)
        print("Pairing successful. Device key saved locally with restricted permissions.")
    if not KEY_FILE.is_file():
        raise SystemExit("Missing .agent_key. Pair this device from the website first.")
    token = KEY_FILE.read_text().strip()
    if len(token) < 32:
        raise SystemExit("Local device key is invalid.")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    print("NoRestrictions Agent connected. Workspace:", WORKSPACE)
    print("Enabled tasks: device_info, list_files, read_file, write_file. No remote shell execution.")
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
                    await asyncio.sleep(4)
                    continue
                task_id = task.get("id", "")
                try:
                    result = handle_task(task)
                    success = True
                    print(f"Task {task_id} completed: {task.get('kind')}")
                except Exception as exc:
                    result = str(exc)[:500]
                    success = False
                    print("Task failed:", result)
                done = await client.post(BASE + "/tasks/complete", headers=headers,
                    json={"task_id": task_id, "success": success, "result": result})
                done.raise_for_status()
            except httpx.HTTPError as exc:
                print("Connection/task error:", str(exc)[:200])
                await asyncio.sleep(8)
            except (KeyboardInterrupt, asyncio.CancelledError):
                break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAgent stopped.")
