import os
import sys
import time
import json
import platform
import urllib.request
import urllib.error
from pathlib import Path

SERVER = "https://norestrictions-api.sdrhaldwane.workers.dev"

KEY_FILE = Path.home() / ".nr_agent_key"
POLL_INTERVAL = 2
PING_INTERVAL = 10

device_key = None
last_ping = 0


def request(path, method="GET", data=None):
    url = SERVER + path

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "NoRestrictions-Agent/4.3"
    }

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    except urllib.error.HTTPError as e:
        try:
            message = e.read().decode("utf-8")
        except Exception:
            message = str(e)

        print("HTTP Error:", e.code, message)
        return None

    except Exception as e:
        print("Connection Error:", e)
        return None


def get_device_key():
    global device_key

    print("\n=== NoRestrictions AI ===")
    print("الصق مفتاح الربط الذي نسخته من الموقع.")
    print("")

    key = input("Device Key: ").strip()

    if not key:
        print("لم تدخل مفتاحاً.")
        sys.exit(1)

    if len(key) < 32:
        print("المفتاح غير صالح أو قصير.")
        sys.exit(1)

    device_key = key
    KEY_FILE.write_text(key, encoding="utf-8")


def pair_device():
    print("\nجاري ربط الجهاز...")

    result = request(
        "/api/device/pair",
        method="POST",
        data={
            "key": device_key,
            "kind": "termux",
            "info": {
                "platform": platform.platform(),
                "python": platform.python_version()
            }
        }
    )

    if result is None:
        print("فشل الاتصال بالخادم.")
        return False

    if result.get("error"):
        print("فشل الربط:", result["error"])
        return False

    print("تم إرسال طلب الربط.")
    return True


def ping():
    global last_ping

    now = time.time()

    if now - last_ping < PING_INTERVAL:
        return

    result = request(
        "/api/device/ping",
        method="POST",
        data={"key": device_key}
    )

    if result is not None:
        last_ping = now


def poll_job():
    return request(
        "/api/device/poll?key=" + device_key
    )


def send_result(job_id, output, exit_code=0):
    return request(
        "/api/device/done",
        method="POST",
        data={
            "key": device_key,
            "id": job_id,
            "output": str(output),
            "exit_code": exit_code
        }
    )


def safe_path(path):
    base = Path.home().resolve()
    target = (base / path).resolve()

    if target != base and base not in target.parents:
        raise ValueError("المسار خارج مجلد Termux المسموح.")

    return target


def execute_command(command):
    command = str(command).strip()

    if command == "pwd":
        return str(Path.cwd()), 0

    if command == "whoami":
        return os.environ.get("USER", "unknown"), 0

    if command == "date":
        return time.ctime(), 0

    if command == "uname":
        return platform.platform(), 0

    if command == "help":
        return (
            "الأوامر المتاحة:\n"
            "pwd\n"
            "whoami\n"
            "date\n"
            "uname\n"
            "python --version\n"
            "ls\n"
            "cat <filename>\n"
        ), 0

    if command == "python --version":
        return platform.python_version(), 0

    if command == "ls":
        files = list(Path.home().iterdir())
        return "\n".join(x.name for x in files), 0

    if command.startswith("cat "):
        filename = command[4:].strip()

        if not filename:
            return "حدد اسم الملف.", 1

        target = safe_path(filename)

        if not target.is_file():
            return "الملف غير موجود.", 1

        content = target.read_text(
            encoding="utf-8",
            errors="replace"
        )

        return content[:20000], 0

    return "هذه العملية غير مدعومة في Agent 4.3.", 1


def process_job(job):
    job_id = job.get("id")
    command = job.get("command")

    if not job_id or not command:
        return

    print("\nوصل طلب جديد:", command)

    try:
        output, code = execute_command(command)

    except Exception as e:
        output = str(e)
        code = 1

    send_result(job_id, output, code)
    print("تم إرسال النتيجة.")


def main():
    get_device_key()

    if not pair_device():
        print("تعذر إكمال الربط. تحقق من المفتاح والخادم.")
        return

    print("\nAgent يعمل الآن.")
    print("اترك Termux مفتوحاً لاستقبال الطلبات.")
    print("اضغط Ctrl+C للإيقاف.\n")

    while True:
        try:
            ping()

            result = poll_job()

            if result:
                job = result.get("job")

                if job:
                    process_job(job)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nتم إيقاف Agent.")
            break

        except Exception as e:
            print("خطأ:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
