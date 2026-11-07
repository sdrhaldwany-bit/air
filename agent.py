import os
import sys
import time
import json
import socket
import platform
import urllib.request
import urllib.parse
import urllib.error
import subprocess
import traceback

# ==================================
# NoRestrictions AI - Termux Agent
# ==================================

VERSION = "5.0"

SERVER = os.environ.get(
    "NR_SERVER",
    "https://norestrictions-api.sdrhaldwane.workers.dev"
).rstrip("/")

DEVICE_KEY = (
    sys.argv[1]
    if len(sys.argv) > 1
    else os.environ.get("NR_DEVICE_KEY", "")
)

POLL_INTERVAL = 4
RUNNING = True


# ==================================
# HTTP
# ==================================

def request(method, path, data=None):

    url = SERVER + path

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "NoRestrictions-Agent/5.0"
    }

    if data is not None:
        data["device_key"] = DEVICE_KEY

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

    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise Exception(
            "HTTP {}: {}".format(error.code, detail[:500])
        )

    except Exception as error:
        raise Exception(str(error))


# ==================================
# DEVICE INFORMATION
# ==================================

def device_info():

    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "python": platform.python_version()
    }


# ==================================
# NETWORK INFORMATION
# ==================================

def network_info():

    result = {
        "hostname": socket.gethostname(),
        "local_ip": "غير معروف",
        "dns": "غير معروف"
    }

    try:
        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        sock.connect(("1.1.1.1", 80))

        result["local_ip"] = sock.getsockname()[0]

        sock.close()

    except Exception:
        pass

    try:
        result["dns"] = socket.gethostbyname("example.com")

    except Exception as error:
        result["dns"] = "فشل DNS: " + str(error)

    return result


# ==================================
# INTERNET CHECK
# ==================================

def internet_check():

    urls = [
        "https://www.cloudflare.com",
        "https://www.google.com"
    ]

    results = []

    for url in urls:

        try:
            start = time.time()

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "NoRestrictions-Agent/5.0"
                }
            )

            with urllib.request.urlopen(req, timeout=8) as response:
                elapsed = round(
                    (time.time() - start) * 1000
                )

                results.append({
                    "url": url,
                    "status": response.status,
                    "latency_ms": elapsed,
                    "success": True
                })

        except Exception as error:

            results.append({
                "url": url,
                "success": False,
                "error": str(error)
            })

    return {
        "tests": results
    }


# ==================================
# DNS CHECK
# ==================================

def dns_check():

    domains = [
        "example.com",
        "cloudflare.com",
        "google.com"
    ]

    results = []

    for domain in domains:

        try:
            addresses = socket.getaddrinfo(
                domain,
                None,
                socket.AF_INET
            )

            ips = sorted(set(
                item[4][0] for item in addresses
            ))

            results.append({
                "domain": domain,
                "success": True,
                "addresses": ips
            })

        except Exception as error:

            results.append({
                "domain": domain,
                "success": False,
                "error": str(error)
            })

    return {
        "results": results
    }


# ==================================
# ALLOWED TASKS
# ==================================

def execute_task(command):

    command = str(command).strip().lower()

    if command == "help":
        return """
الأوامر المسموحة:

help
whoami
date
device_info
network_info
internet_check
dns_check
"""

    if command == "whoami":
        return os.environ.get(
            "USER",
            "unknown"
        )

    if command == "date":
        return time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    if command == "device_info":
        return device_info()

    if command == "network_info":
        return network_info()

    if command == "internet_check":
        return internet_check()

    if command == "dns_check":
        return dns_check()

    return {
        "error": "هذا الأمر غير مسموح",
        "command": command
    }


# ==================================
# JOB POLLING
# ==================================

def poll_job():

    query = urllib.parse.urlencode({
        "device_key": DEVICE_KEY
    })

    return request(
        "GET",
        "/api/device/poll?" + query
    )


# ==================================
# SEND RESULT
# ==================================

def send_result(job_id, output, exit_code=0):

    return request(
        "POST",
        "/api/device/done",
        {
            "id": job_id,
            "output": json.dumps(
                output,
                ensure_ascii=False
            ) if not isinstance(output, str) else output,
            "exit_code": exit_code
        }
    )


# ==================================
# MAIN LOOP
# ==================================

def main():

    global RUNNING

    if not DEVICE_KEY:
        print("خطأ: مفتاح الجهاز غير موجود.")
        print("شغّل البرنامج مع مفتاح الجهاز.")
        return

    if not SERVER.startswith("https://"):
        print("خطأ: يجب استخدام اتصال HTTPS.")
        return

    print("=" * 42)
    print(" NoRestrictions AI Agent")
    print(" Version:", VERSION)
    print("=" * 42)

    print("[+] Server:", SERVER)
    print("[+] Device key: موجود")
    print("[+] Agent started")
    print("[+] Waiting for tasks...")
    print()

    while RUNNING:

        try:

            data = poll_job()

            job = data.get("job")

            if not job:
                time.sleep(POLL_INTERVAL)
                continue

            job_id = job.get("id")
            command = job.get("command")

            if not job_id or not command:
                time.sleep(POLL_INTERVAL)
                continue

            print("[TASK]", command)

            try:

                output = execute_task(command)

                send_result(
                    job_id,
                    output,
                    0
                )

                print("[OK] Task completed")

            except Exception as error:

                send_result(
                    job_id,
                    str(error),
                    1
                )

                print("[ERROR]", error)

        except KeyboardInterrupt:

            RUNNING = False
            print("\nAgent stopped.")

        except Exception as error:

            print("[CONNECTION ERROR]", error)
            time.sleep(8)


if __name__ == "__main__":
    main()
