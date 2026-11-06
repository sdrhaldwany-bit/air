#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NoRestrictions AI - Safe Termux Agent
Version: 3.0
"""

import os
import sys
import re
import json
import time
import hashlib
import platform
import subprocess
import urllib.request
import urllib.error
import threading
import shlex
from pathlib import Path

SERVER = os.environ.get(
    "NR_SERVER",
    "https://norestrictions-api.sdrhaldwane.workers.dev"
).rstrip("/")

KEY_FILE = Path.home() / ".nr_agent_key"
VERSION = "3.0"
MAX_OUTPUT = 12000
TIMEOUT = 15

HOME = Path.home().resolve()


def get_key():
    key = sys.argv[1] if len(sys.argv) > 1 else ""

    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()

    while not re.fullmatch(r"[a-f0-9]{64}", key or ""):
        key = input("Device Key: ").strip().lower()

    try:
        KEY_FILE.write_text(key)
        KEY_FILE.chmod(0o600)
    except OSError:
        pass

    return key


def request_api(action, data=None, method="POST"):
    url = SERVER + "/api/device/" + action

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "NoRestrictions-Agent/" + VERSION
    }

    body = json.dumps(data or {}).encode() if method == "POST" else None

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def safe_path(value):
    path = (HOME / value).resolve()

    if path != HOME and HOME not in path.parents:
        raise ValueError("الوصول خارج مجلد المستخدم غير مسموح")

    return path


def execute(command):
    try:
        parts = shlex.split(command)

        if not parts:
            return "الأمر فارغ", 1

        action = parts[0]

        if action == "pwd" and len(parts) == 1:
            return str(HOME), 0

        if action == "whoami" and len(parts) == 1:
            return os.environ.get("USER", "termux"), 0

        if action == "date" and len(parts) == 1:
            return time.strftime("%Y-%m-%d %H:%M:%S"), 0

        if action == "python" and parts[1:] == ["--version"]:
            return platform.python_version(), 0

        if action == "uname" and len(parts) == 1:
            return platform.platform(), 0

        if action == "ls" and len(parts) <= 2:
            target = safe_path(parts[1] if len(parts) == 2 else ".")
            if not target.is_dir():
                return "المسار ليس مجلداً", 1

            return "\n".join(sorted(p.name for p in target.iterdir())), 0

        if action == "cat" and len(parts) == 2:
            target = safe_path(parts[1])

            if not target.is_file():
                return "الملف غير موجود", 1

            if target.stat().st_size > 32000:
                return "الملف أكبر من الحد المسموح", 1

            return target.read_text(errors="replace"), 0

        if action == "help" and len(parts) == 1:
            return (
                "الأوامر المتاحة:\n"
                "pwd\nwhoami\ndate\npython --version\n"
                "uname\nls [مسار]\ncat [ملف]\nhelp"
            ), 0

        return (
            "هذا الأمر غير مدعوم في النسخة الآمنة من الوكيل."
        ), 126

    except Exception as error:
        return "خطأ: " + str(error), 1


def send_result(key, job_id, output, code):
    return request_api("done", {
        "key": key,
        "id": job_id,
        "output": output[-MAX_OUTPUT:],
        "exitCode": code
    })


def handle_job(key, job):
    job_id = job.get("id")
    command = str(job.get("command", ""))

    if not isinstance(job_id, int):
        return

    print("\n▶ المهمة:", command)

    output, code = execute(command)

    print(output[:1000])

    try:
        send_result(key, job_id, output, code)
        print("✓ تم إرسال النتيجة")
    except Exception as error:
        print("تعذر إرسال النتيجة:", error)


def heartbeat(key):
    while True:
        try:
            request_api("ping", {"key": key})
        except Exception:
            pass

        time.sleep(10)


def main():
    key = get_key()

    print("=" * 40)
    print("NoRestrictions AI Agent")
    print("Version:", VERSION)
    print("Device:", platform.machine())
    print("Server:", SERVER)
    print("=" * 40)

    threading.Thread(
        target=heartbeat,
        args=(key,),
        daemon=True
    ).start()

    delay = 2

    while True:
        try:
            result = request_api("poll", {
                "key": key,
                "kind": "termux",
                "info": platform.platform(),
                "wait": 20
            })

            delay = 2

            for job in result.get("jobs", []):
                threading.Thread(
                    target=handle_job,
                    args=(key, job),
                    daemon=True
                ).start()

        except KeyboardInterrupt:
            print("\nتم إيقاف الوكيل.")
            break

        except Exception as error:
            print("الاتصال غير متاح:", error)
            time.sleep(delay)
            delay = min(delay * 2, 20)


if __name__ == "__main__":
    main()
