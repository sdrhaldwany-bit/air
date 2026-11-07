#!/usr/bin/env python3
# NoRestrictions AI - Termux Agent 4.1

import os
import sys
import time
import json
import shlex
import signal
import secrets
import platform
import pathlib
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# ==============================
# CONFIGURATION
# ==============================

SERVER = "https://norestrictions-api.sdrhaldwane.workers.dev"

HOME = pathlib.Path.home().resolve()
KEY_FILE = HOME / ".nr_agent_key"

POLL_INTERVAL = 2
PING_INTERVAL = 10
MAX_OUTPUT = 12000
REQUEST_TIMEOUT = 20

running = True


# ==============================
# STOP HANDLER
# ==============================

def stop_agent(signum, frame):
    global running
    running = False
    print("\nStopping agent...")


signal.signal(signal.SIGINT, stop_agent)
signal.signal(signal.SIGTERM, stop_agent)


# ==============================
# DEVICE KEY
# ==============================

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


# ==============================
# HTTP REQUEST
# ==============================

def request_api(endpoint, data=None, method="POST"):
    url = SERVER + "/api/device/" + endpoint

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "NoRestrictions-Termux-Agent/4.1"
    }

    body = None

    if data is not None:
        body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT
        ) as response:

            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        print("HTTP error:", error.code, message[:300])
        return None

    except Exception as error:
        print("Connection error:", str(error))
        return None


# ==============================
# PAIR DEVICE
# ==============================

def pair_device(key):
    result = request_api(
        "pair",
        {
            "key": key,
            "kind": "Termux",
            "info": (
                "Android Termux | " +
                platform.machine()
            )
        }
    )

    if result is None:
        print("Pairing failed.")
        return False

    if result.get("error"):
        print("Pairing rejected:", result["error"])
        return False

    print("Device pairing checked.")
    return True


# ==============================
# SAFE PATH
# ==============================

def safe_path(value):
    try:
        path = pathlib.Path(value).expanduser()

        if not path.is_absolute():
            path = HOME / path

        resolved = path.resolve()

        resolved.relative_to(HOME)

        return resolved

    except (ValueError, OSError):
        raise ValueError("Path is outside the allowed home directory.")


# ==============================
# COMMAND EXECUTION
# ==============================

def execute(command):
    try:
        parts = shlex.split(command)

        if not parts:
            return "Empty command.", 1

        name = parts[0]

        # HELP
        if name == "help" and len(parts) == 1:
            return (
                "Available operations:\n"
                "pwd\n"
                "whoami\n"
                "date\n"
                "uname\n"
                "python --version\n"
                "ls [path]\n"
                "cat [file]\n"
                "help"
            ), 0

        # PWD
        if name == "pwd" and len(parts) == 1:
            return os.getcwd(), 0

        # WHOAMI
        if name == "whoami" and len(parts) == 1:
            return os.getenv("USER", "unknown"), 0

        # DATE
        if name == "date" and len(parts) == 1:
            return datetime.now().astimezone().isoformat(), 0

        # UNAME
        if name == "uname" and len(parts) == 1:
            return platform.platform(), 0

        # PYTHON VERSION
        if (
            name == "python"
            and len(parts) == 2
            and parts[1] == "--version"
        ):
            return sys.version, 0

        # LIST FILES
        if name == "ls" and len(parts) <= 2:
            target = safe_path(parts[1] if len(parts) == 2 else ".")

            if not target.exists():
                return "Path does not exist.", 1

            if not target.is_dir():
                return target.name, 0

            entries = sorted(
                target.iterdir(),
                key=lambda item: item.name.lower()
            )

            lines = []

            for item in entries[:300]:
                suffix = "/" if item.is_dir() else ""
                lines.append(item.name + suffix)

            return "\n".join(lines) or "Directory is empty.", 0

        # READ FILE
        if name == "cat" and len(parts) == 2:
            target = safe_path(parts[1])

            if not target.exists():
                return "File does not exist.", 1

            if not target.is_file():
                return "Not a regular file.", 1

            if target.stat().st_size > MAX_OUTPUT:
                return "File is too large to read.", 1

            content = target.read_text(
                encoding="utf-8",
                errors="replace"
            )

            return content[:MAX_OUTPUT], 0

        return (
            "Operation not allowed.\n"
            "Use help to see available operations."
        ), 1

    except ValueError as error:
        return str(error), 1

    except Exception as error:
        return "Execution error: " + str(error), 1


# ==============================
# SEND RESULT
# ==============================

def send_result(key, job_id, output, exit_code):
    return request_api(
        "done",
        {
            "key": key,
            "id": job_id,
            "output": str(output)[-MAX_OUTPUT:],
            "exit_code": int(exit_code)
        }
    )


# ==============================
# HANDLE JOB
# ==============================

def handle_job(key, job):
    if not isinstance(job, dict):
        return

    job_id = job.get("id")
    command = job.get("command")

    if job_id is None or not isinstance(command, str):
        print("Invalid job received.")
        return

    print("\nNew task:", command)

    output, exit_code = execute(command)

    print(output)

    result = send_result(
        key,
        job_id,
        output,
        exit_code
    )

    if result is not None:
        print("Result submitted.")
    else:
        print("Could not submit result.")


# ==============================
# HEARTBEAT
# ==============================

def ping_device(key):
    return request_api(
        "ping",
        {
            "key": key,
            "kind": "Termux",
            "info": platform.platform()
        }
    )


# ==============================
# POLL JOB
# ==============================

def poll_job(key):
    return request_api(
        "poll",
        {
            "key": key
        }
    )


# ==============================
# MAIN LOOP
# ==============================

def main():
    print("=" * 40)
    print(" NoRestrictions AI - Termux Agent 4.1")
    print("=" * 40)

    key = get_key()

    print("Connecting to server...")

    if not pair_device(key):
        print("Unable to pair device.")
        return

    print("Agent started successfully.")
    print("Waiting for tasks...\n")

    last_ping = 0

    while running:

        current_time = time.time()

        # HEARTBEAT
        if current_time - last_ping >= PING_INTERVAL:
            ping_device(key)
            last_ping = current_time

        # POLL
        result = poll_job(key)

        if result is None:
            time.sleep(POLL_INTERVAL)
            continue

        # IMPORTANT:
        # Worker returns a singular "job", not "jobs".

        job = result.get("job")

        if job and running:
            handle_job(key, job)

        time.sleep(POLL_INTERVAL)

    print("Agent stopped.")


# ==============================
# START
# ==============================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print("\nAgent stopped.")

    except Exception as error:
        print("Fatal error:", error)
