import os
import sys
import time
import json
import socket
import platform
import getpass
import urllib.request
import urllib.error
from datetime import datetime

VERSION = "6.0"
SERVER = os.environ.get(
    "NR_SERVER",
    "https://norestrictions-api.sdrhaldwane.workers.dev"
).rstrip("/")

DEVICE_KEY = ""

POLL_INTERVAL = 3
REQUEST_TIMEOUT = 15


def api_request(path, method="GET", data=None):
    url = SERVER + path

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "NoRestrictions-Agent/" + VERSION
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

    with urllib.request.urlopen(
        request,
        timeout=REQUEST_TIMEOUT
    ) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw)


def get_device_info():
    return (
        "النظام: " + platform.system() + "\n"
        "الإصدار: " + platform.release() + "\n"
        "المعمارية: " + platform.machine() + "\n"
        "Python: " + platform.python_version() + "\n"
        "اسم الجهاز: " + socket.gethostname()
    )


def get_network_info():
    hostname = socket.gethostname()

    try:
        ip = socket.gethostbyname(hostname)
    except Exception:
        ip = "غير متاح"

    return (
        "اسم المضيف: " + hostname + "\n"
        "عنوان IP المحلي: " + ip
    )


def internet_check():
    try:
        request = urllib.request.Request(
            "https://www.google.com/generate_204",
            headers={"User-Agent": "NoRestrictions-Agent"}
        )

        with urllib.request.urlopen(
            request,
            timeout=8
        ) as response:
            return "الاتصال بالإنترنت يعمل ✓"

    except Exception as error:
        return "تعذر التحقق من الإنترنت: " + str(error)


def dns_check():
    try:
        result = socket.getaddrinfo(
            "example.com",
            443,
            type=socket.SOCK_STREAM
        )

        addresses = sorted(set(
            item[4][0] for item in result
        ))

        return "نتيجة DNS:\n" + "\n".join(addresses[:5])

    except Exception as error:
        return "فشل فحص DNS: " + str(error)


def execute_command(command):
    command = str(command).strip().lower()

    if command == "help":
        return (
            "الأوامر المتاحة:\n"
            "help\n"
            "whoami\n"
            "date\n"
            "device_info\n"
            "network_info\n"
            "internet_check\n"
            "dns_check"
        ), 0

    if command == "whoami":
        return "المستخدم الحالي: " + getpass.getuser(), 0

    if command == "date":
        return datetime.now().astimezone().isoformat(
            timespec="seconds"
        ), 0

    if command == "device_info":
        return get_device_info(), 0

    if command == "network_info":
        return get_network_info(), 0

    if command == "internet_check":
        return internet_check(), 0

    if command == "dns_check":
        return dns_check(), 0

    return "هذا الطلب غير موجود ضمن قائمة العمليات المسموحة.", 1


def poll_tasks():
    path = "/api/device/poll?key=" + DEVICE_KEY
    return api_request(path)


def send_result(job_id, output, exit_code):
    return api_request(
        "/api/device/done",
        method="POST",
        data={
            "key": DEVICE_KEY,
            "id": job_id,
            "output": str(output)[:10000],
            "exit_code": int(exit_code)
        }
    )


def main():
    global DEVICE_KEY

    if len(sys.argv) >= 2:
        DEVICE_KEY = sys.argv[1].strip()
    else:
        DEVICE_KEY = input("الصق مفتاح الجهاز: ").strip()

    if len(DEVICE_KEY) != 64:
        print("[!] مفتاح الجهاز غير صالح.")
        return

    if any(c not in "0123456789abcdefABCDEF" for c in DEVICE_KEY):
        print("[!] صيغة المفتاح غير صحيحة.")
        return

    print("=" * 40)
    print("NoRestrictions AI Agent")
    print("Version:", VERSION)
    print("Server:", SERVER)
    print("[+] Device key: موجود")
    print("=" * 40)

    print("[+] جاري الاتصال بالخادم...")

    try:
        result = poll_tasks()

        if not result.get("success"):
            print("[!] تعذر تسجيل الجهاز:", result)
            return

    except Exception as error:
        print("[!] فشل الاتصال:", error)
        return

    print("[+] Agent started")
    print("[+] Waiting for tasks...")

    while True:
        try:
            result = poll_tasks()

            if not result.get("success"):
                print("[!] استجابة غير ناجحة من الخادم.")
                time.sleep(POLL_INTERVAL)
                continue

            jobs = result.get("jobs", [])

            for job in jobs:
                job_id = job.get("id")
                command = job.get("command", "")

                if not job_id:
                    continue

                print("[+] Task received:", job_id)
                print("[+] Operation:", command)

                try:
                    output, exit_code = execute_command(command)

                except Exception as error:
                    output = "حدث خطأ أثناء العملية: " + str(error)
                    exit_code = 1

                try:
                    send_result(job_id, output, exit_code)
                    print("[+] Result sent:", job_id)

                except Exception as error:
                    print("[!] تعذر إرسال النتيجة:", error)

        except KeyboardInterrupt:
            print("\n[+] Agent stopped.")
            break

        except urllib.error.HTTPError as error:
            print("[!] HTTP Error:", error.code)
            time.sleep(POLL_INTERVAL)

        except Exception as error:
            print("[!] Connection error:", error)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
