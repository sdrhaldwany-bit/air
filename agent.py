import os
import sys
import json
import time
import secrets
import pathlib
import subprocess
import shlex
import urllib.request
import urllib.error
from datetime import datetime

# =====================================
# NoRestrictions AI - Termux Agent 4.2
# =====================================

SERVER = "https://norestrictions-api.sdrhaldwane.workers.dev"

HOME = pathlib.Path.home().resolve()
KEY_FILE = HOME / ".nr_agent_key"

POLL_INTERVAL = 2
PING_INTERVAL = 10
REQUEST_TIMEOUT = 20

running = True


# =====================================
# KEY
# =====================================

def get_key():
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()

        if len(key) == 64:
            return key

    key = secrets.token_hex(32)
    KEY_FILE.write_text(key)

    try:
        KEY_FILE.chmod(0o600)
    except OSError:
        pass

    return key


KEY = get_key()


# =====================================
# HTTP
# =====================================

def request(path, data=None, method="POST"):
    url = SERVER + path

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "NoRestrictions-Agent/4.2"
    }

    payload = None

    if data is not None:
        payload = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=REQUEST_TIMEOUT
        ) as response:
            raw = response.read().decode("utf-8", errors="replace")

            if not raw:
                return {}

            return json.loads(raw)

    except urllib.error.HTTPError as e:
        message = e.read().decode("utf-8", errors="replace")
        raise Exception(
            f"HTTP {e.code}: {message[:300]}"
        )

    except urllib.error.URLError as e:
        raise Exception(f"Network error: {e.reason}")


# =====================================
# PAIR DEVICE
# =====================================

def pair_device():
    print("\n[*] Connecting device...")

    result = request(
        "/api/device/pair",
        {
            "key": KEY,
            "kind": "Termux",
            "info": "Android Termux Agent 4.2"
        }
    )

    if not result.get("ok"):
        raise Exception("Device pairing failed")

    print("[+] Device paired successfully.")

    print("\n" + "=" * 45)
    print("DEVICE KEY - COPY THIS INTO YOUR WEBSITE")
    print("=" * 45)
    print(KEY)
    print("=" * 45 + "\n")


# =====================================
# PING
# =====================================

def ping():
    try:
        request(
            "/api/device/ping",
            {
                "key": KEY,
                "info": "Online - Agent 4.2"
            }
        )

        return True

    except Exception as e:
        print("[PING ERROR]", e)
        return False


# =====================================
# SAFE PATH
# =====================================

def safe_path(path):
    if not isinstance(path, str):
        raise ValueError("Invalid path")

    if not path or len(path) > 300:
        raise ValueError("Invalid path length")

    if ".." in pathlib.PurePosixPath(path).parts:
        raise ValueError("Parent directory access is blocked")

    candidate = (HOME / path).resolve()

    try:
        candidate.relative_to(HOME)
    except ValueError:
        raise ValueError("Access outside Termux home is blocked")

    return candidate


# =====================================
# COMMAND EXECUTOR
# =====================================

def execute_command(command):
    if not isinstance(command, str):
        return "Invalid command", 1

    try:
        args = shlex.split(command)
    except ValueError:
        return "Invalid command format", 1

    if not args:
        return "Empty command", 1

    operation = args[0]

    # pwd
    if operation == "pwd" and len(args) == 1:
        return str(HOME), 0

    # whoami
    if operation == "whoami" and len(args) == 1:
        try:
            result = subprocess.run(
                ["whoami"],
                cwd=str(HOME),
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout or result.stderr, result.returncode
        except Exception as e:
            return str(e), 1

    # date
    if operation == "date" and len(args) == 1:
        return datetime.now().astimezone().isoformat(), 0

    # uname
    if operation == "uname" and len(args) == 1:
        try:
            result = subprocess.run(
                ["uname"],
                cwd=str(HOME),
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout or result.stderr, result.returncode
        except Exception as e:
            return str(e), 1

    # python --version
    if operation == "python" and args == ["python", "--version"]:
        try:
            result = subprocess.run(
                [sys.executable, "--version"],
                cwd=str(HOME),
                capture_output=True,
                text=True,
                timeout=10
            )

            output = result.stdout or result.stderr
            return output, result.returncode

        except Exception as e:
            return str(e), 1

    # help
    if operation == "help" and len(args) == 1:
        return (
            "Available operations:\n"
            "pwd\n"
            "whoami\n"
            "date\n"
            "uname\n"
            "python --version\n"
            "ls [path]\n"
            "cat [path]\n"
            "help",
            0
        )

    # ls
    if operation == "ls" and len(args) <= 2:
        path = args[1] if len(args) == 2 else "."

        try:
            target = safe_path(path)

            if not target.exists():
                return "Path does not exist", 1

            if not target.is_dir():
                return "Path is not a directory", 1

            entries = sorted(os.listdir(target))

            if not entries:
                return "Directory is empty", 0

            return "\n".join(entries[:300]), 0

        except Exception as e:
            return str(e), 1

    # cat
    if operation == "cat" and len(args) == 2:
        try:
            target = safe_path(args[1])

            if not target.exists():
                return "File does not exist", 1

            if not target.is_file():
                return "Not a file", 1

            if target.stat().st_size > 50000:
                return "File is too large (50 KB limit)", 1

            content = target.read_text(
                encoding="utf-8",
                errors="replace"
            )

            return content[:12000], 0

        except Exception as e:
            return str(e), 1

    return "Operation not allowed by Agent 4.2", 1


# =====================================
# POLL JOB
# =====================================

def poll_job():
    result = request(
        "/api/device/poll",
        {"key": KEY}
    )

    return result.get("job")


# =====================================
# SEND RESULT
# =====================================

def send_result(job_id, output, exit_code):
    return request(
        "/api/device/done",
        {
            "key": KEY,
            "id": int(job_id),
            "output": str(output)[:12000],
            "exit_code": int(exit_code)
        }
    )


# =====================================
# PROCESS JOB
# =====================================

def process_job(job):
    job_id = job.get("id")
    command = job.get("command")

    if not job_id or not command:
        print("[!] Invalid job received")
        return

    print("\n[JOB]", job_id)
    print("[COMMAND]", command)

    try:
        output, exit_code = execute_command(command)

    except Exception as e:
        output = str(e)
        exit_code = 1

    try:
        send_result(job_id, output, exit_code)

        print("[+] Result sent successfully")
        print(output[:1000])

    except Exception as e:
        print("[RESULT ERROR]", e)


# =====================================
# MAIN LOOP
# =====================================

def main():
    global running

    print("=" * 45)
    print(" NoRestrictions AI - Agent 4.2")
    print("=" * 45)

    print("[*] Server:", SERVER)
    print("[*] Home:", HOME)

    try:
        pair_device()
    except Exception as e:
        print("[PAIR ERROR]", e)
        print("Check your internet and Worker deployment.")
        return

    last_ping = 0

    print("[+] Agent started.")
    print("[*] Waiting for jobs...\n")

    while running:
        try:
            now = time.time()

            if now - last_ping >= PING_INTERVAL:
                if ping():
                    print("[ONLINE] Device heartbeat OK")

                last_ping = now

            job = poll_job()

            if job:
                process_job(job)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n[!] Agent stopped by user.")
            running = False

        except Exception as e:
            print("[AGENT ERROR]", e)
            time.sleep(5)

    print("[*] Agent stopped.")


# =====================================
# START
# =====================================

if __name__ == "__main__":
    main()
