#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NoRestrictions AI Agent
Version: 4.0
Termux Agent
"""

import os
import sys
import re
import json
import time
import platform
import urllib.request
import urllib.error
import threading
import shlex
import secrets
import logging

from pathlib import Path
from datetime import datetime

# ==============================
# CONFIGURATION
# ==============================

SERVER = os.environ.get(
    "NR_SERVER",
    "https://norestrictions-api.sdrhaldwane.workers.dev"
).rstrip("/")

VERSION = "4.0"

HOME = Path.home().resolve()
KEY_FILE = HOME / ".nr_agent_key"
LOG_FILE = HOME / ".nr_agent.log"

MAX_OUTPUT = 12000
MAX_FILE_SIZE = 32000
REQUEST_TIMEOUT = 25
HEARTBEAT_INTERVAL = 10
POLL_INTERVAL = 2

running = True
job_lock = threading.Lock()

# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

log = logging.getLogger("NoRestrictions")


# ==============================
# DEVICE KEY
# ==============================

def get_key():

    key = sys.argv[1] if len(sys.argv) > 1 else ""

    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()

    if not re.fullmatch(r"[a-f0-9]{64}", key or ""):
        key = secrets.token_hex(32)
        log.warning("تم إنشاء مفتاح جديد.")

    KEY_FILE.write_text(key)
    KEY_FILE.chmod(0o600)

    return key


# ==============================
# HTTP CLIENT
# ==============================

def request_api(action, data=None, method="POST"):

    url = SERVER + "/api/device/" + action

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "NoRestrictions-Agent/" + VERSION
    }

    body = None

    if method == "POST":
        body = json.dumps(
            data or {},
            ensure_ascii=False
        ).encode("utf-8")

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

        detail = error.read().decode(
            errors="replace"
        )

        raise RuntimeError(
            f"HTTP {error.code}: {detail[:1000]}"
        )

    except urllib.error.URLError as error:

        raise ConnectionError(
            "تعذر الاتصال بالخادم: " + str(error.reason)
        )


# ==============================
# PATH SECURITY
# ==============================

def safe_path(value):

    if not value:
        value = "."

    path = (HOME / value).resolve()

    if path != HOME and HOME not in path.parents:
        raise PermissionError(
            "الوصول خارج مجلد Termux HOME غير مسموح."
        )

    return path


# ==============================
# SAFE OPERATIONS
# ==============================

def execute(command):

    try:

        parts = shlex.split(str(command))

        if not parts:
            return "الأمر فارغ.", 1

        action = parts[0]

        # ----------------------
        # PWD
        # ----------------------

        if action == "pwd" and len(parts) == 1:

            return str(HOME), 0

        # ----------------------
        # WHOAMI
        # ----------------------

        if action == "whoami" and len(parts) == 1:

            return os.environ.get(
                "USER",
                "termux"
            ), 0

        # ----------------------
        # DATE
        # ----------------------

        if action == "date" and len(parts) == 1:

            return datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ), 0

        # ----------------------
        # PYTHON VERSION
        # ----------------------

        if action == "python" and parts[1:] == ["--version"]:

            return platform.python_version(), 0

        # ----------------------
        # SYSTEM INFO
        # ----------------------

        if action == "uname" and len(parts) == 1:

            return platform.platform(), 0

        # ----------------------
        # LIST FILES
        # ----------------------

        if action == "ls" and len(parts) <= 2:

            target = safe_path(
                parts[1] if len(parts) == 2 else "."
            )

            if not target.is_dir():
                return "المسار ليس مجلدًا.", 1

            files = sorted(
                item.name +
                ("/" if item.is_dir() else "")
                for item in target.iterdir()
            )

            return "\n".join(files) or "المجلد فارغ.", 0

        # ----------------------
        # READ FILE
        # ----------------------

        if action == "cat" and len(parts) == 2:

            target = safe_path(parts[1])

            if not target.is_file():
                return "الملف غير موجود.", 1

            if target.stat().st_size > MAX_FILE_SIZE:
                return "الملف أكبر من الحد المسموح.", 1

            return target.read_text(
                encoding="utf-8",
                errors="replace"
            ), 0

        # ----------------------
        # HELP
        # ----------------------

        if action == "help" and len(parts) == 1:

            return (
                "NoRestrictions Agent 4.0\n\n"
                "العمليات المتاحة:\n"
                "pwd\n"
                "whoami\n"
                "date\n"
                "python --version\n"
                "uname\n"
                "ls [path]\n"
                "cat [file]\n"
                "help\n"
            ), 0

        return (
            "العملية غير مدعومة في هذا الإصدار."
        ), 126

    except Exception as error:

        return "خطأ: " + str(error), 1


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
            "exitCode": int(exit_code)
        }
    )


# ==============================
# PROCESS JOB
# ==============================

def handle_job(key, job):

    job_id = job.get("id")

    if not isinstance(job_id, int):
        log.warning("تم تجاهل مهمة ذات معرف غير صالح.")
        return

    command = str(job.get("command", ""))

    with job_lock:

        log.info("استلام المهمة رقم %s", job_id)

        output, exit_code = execute(command)

        log.info("نتيجة المهمة:\n%s", output[:1000])

        try:

            send_result(
                key,
                job_id,
                output,
                exit_code
            )

            log.info(
                "تم إرسال نتيجة المهمة رقم %s",
                job_id
            )

        except Exception as error:

            log.error(
                "تعذر إرسال نتيجة المهمة: %s",
                error
            )


# ==============================
# HEARTBEAT
# ==============================

def heartbeat(key):

    while running:

        try:

            request_api(
                "ping",
                {
                    "key": key
                }
            )

        except Exception as error:

            log.warning(
                "تعذر إرسال نبضة الاتصال: %s",
                error
            )

        time.sleep(HEARTBEAT_INTERVAL)


# ==============================
# DEVICE INFORMATION
# ==============================

def device_info():

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "home": str(HOME),
        "version": VERSION
    }


# ==============================
# MAIN
# ==============================

def main():

    global running

    key = get_key()

    print("=" * 45)
    print("       NoRestrictions AI Agent")
    print("              Version 4.0")
    print("=" * 45)

    print("Server:", SERVER)
    print("Device:", platform.machine())
    print("Python:", platform.python_version())
    print("HOME:", HOME)

    # PAIR DEVICE

    try:

        result = request_api(
            "pair",
            {
                "key": key
            }
        )

        if not result.get("ok"):

            log.error(
                "فشل تسجيل الجهاز: %s",
                result
            )

            return

        log.info("تم تسجيل الجهاز بنجاح.")

    except Exception as error:

        log.error(
            "فشل الاتصال الأولي: %s",
            error
        )

        return

    # START HEARTBEAT

    heartbeat_thread = threading.Thread(
        target=heartbeat,
        args=(key,),
        daemon=True
    )

    heartbeat_thread.start()

    log.info("الوكيل يعمل وينتظر المهام.")

    delay = POLL_INTERVAL

    # JOB LOOP

    try:

        while running:

            try:

                result = request_api(
                    "poll",
                    {
                        "key": key,
                        "kind": "termux",
                        "info": json.dumps(
                            device_info(),
                            ensure_ascii=False
                        )
                    }
                )

                delay = POLL_INTERVAL

                jobs = result.get("jobs", [])

                for job in jobs:

                    if not running:
                        break

                    handle_job(key, job)

                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:

                raise

            except Exception as error:

                log.error(
                    "خطأ في الاتصال: %s",
                    error
                )

                time.sleep(delay)

                delay = min(
                    delay * 2,
                    30
                )

    except KeyboardInterrupt:

        running = False

        print("\nتم إيقاف الوكيل.")

    finally:

        running = False

        log.info("انتهى تشغيل الوكيل.")


# ==============================
# ENTRY POINT
# ==============================

if __name__ == "__main__":
    main()
