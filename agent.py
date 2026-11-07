import os
import sys
import time
import json
import socket
import platform
import getpass
import shutil
import urllib.request
import urllib.error

from datetime import datetime

VERSION = "7.0"

SERVER = os.environ.get(
    "NR_SERVER",
    "https://norestrictions-api.sdrhaldwane.workers.dev"
).rstrip("/")

POLL_INTERVAL = 3
REQUEST_TIMEOUT = 20
MAX_OUTPUT = 10000

DEVICE_KEY = ""


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

        if not raw:
            return {}

        return json.loads(raw)


def device_info():

    return "\n".join([
        "Device: " + socket.gethostname(),
        "System: " + platform.system(),
        "Release: " + platform.release(),
        "Architecture: " + platform.machine(),
        "Python: " + platform.python_version(),
        "Processor: " + (platform.processor() or "Unknown"),
        "User: " + getpass.getuser()
    ])


def network_info():

    hostname = socket.gethostname()

    try:
        ip = socket.gethostbyname(hostname)
    except Exception:
        ip = "Unavailable"

    return (
        "Hostname: " + hostname +
        "\nLocal IP: " + ip
    )


def internet_check():

    try:

        request = urllib.request.Request(
            "https://www.google.com/generate_204"
        )

        with urllib.request.urlopen(
            request,
            timeout=8
        ) as response:

            return "Internet connection: OK"

    except Exception as error:

        return "Internet error: " + str(error)


def dns_check():

    try:

        results = socket.getaddrinfo(
            "example.com",
            443,
            type=socket.SOCK_STREAM
        )

        addresses = sorted(set(
            item[4][0] for item in results
        ))

        return "DNS results:\n" + "\n".join(addresses[:5])

    except Exception as error:

        return "DNS error: " + str(error)


def storage_info():

    try:

        usage = shutil.disk_usage(os.path.expanduser("~"))

        return (
            "Total: " + str(round(usage.total / 1024**3, 2)) + " GB\n"
            "Used: " + str(round(usage.used / 1024**3, 2)) + " GB\n"
            "Free: " + str(round(usage.free / 1024**3, 2)) + " GB"
        )

    except Exception as error:

        return str(error)


def execute_command(command):

    command = str(command).strip().lower()

    if command == "help":

        return (
            "Available operations:\n"
            "help\n"
            "whoami\n"
            "date\n"
            "device_info\n"
            "network_info\n"
            "internet_check\n"
            "dns_check\n"
            "storage_info"
        ), 0

    if command == "whoami":

        return getpass.getuser(), 0

    if command == "date":

        return datetime.now().astimezone().isoformat(), 0

    if command == "device_info":

        return device_info(), 0

    if command == "network_info":

        return network_info(), 0

    if command == "internet_check":

        return internet_check(), 0

    if command == "dns_check":

        return dns_check(), 0

    if command == "storage_info":

        return storage_info(), 0

    return "Unsupported operation.", 1


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
            "output": str(output)[:MAX_OUTPUT],
            "exit_code": int(exit_code)
        }
    )


def validate_key(key):

    if len(key) != 64:
        return False

    return all(
        char in "0123456789abcdefABCDEF"
        for char in key
    )


def main():

    global DEVICE_KEY

    if len(sys.argv) >= 2:
        DEVICE_KEY = sys.argv[1].strip()
    else:
        DEVICE_KEY = input("Device key: ").strip()

    if not validate_key(DEVICE_KEY):

        print("[!] Invalid device key.")
        return

    print("=" * 45)
    print("NoRestrictions AI Agent")
    print("Version:", VERSION)
    print("Server:", SERVER)
    print("Device key: Loaded")
    print("=" * 45)

    print("[+] Connecting...")

    try:

        result = poll_tasks()

        if not result.get("success"):

            print("[!] Server rejected connection.")
            return

    except Exception as error:

        print("[!] Connection failed:", error)
        return

    print("[+] Agent connected")
    print("[+] Waiting for tasks...")

    while True:

        try:

            result = poll_tasks()

            if not result.get("success"):

                time.sleep(POLL_INTERVAL)
                continue

            jobs = result.get("jobs", [])

            for job in jobs:

                job_id = job.get("id")
                command = job.get("command", "")

                if not job_id:
                    continue

                print("\n" + "=" * 45)
                print("[+] Task:", job_id)
                print("[+] Operation:", command)

                try:

                    output, exit_code = execute_command(command)

                except Exception as error:

                    output = "Execution error: " + str(error)
                    exit_code = 1

                print(output)

                try:

                    send_result(
                        job_id,
                        output,
                        exit_code
                    )

                    print("[+] Result delivered")

                except Exception as error:

                    print("[!] Result delivery failed:", error)

        except KeyboardInterrupt:

            print("\n[+] Agent stopped.")
            break

        except urllib.error.HTTPError as error:

            print("[!] HTTP:", error.code)
            time.sleep(POLL_INTERVAL)

        except Exception as error:

            print("[!] Connection error:", error)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
