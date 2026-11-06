#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NoRestrictions AI — وكيل الجهاز (Termux / Pydroid 3)

يربط هاتفك بصفحة الدردشة: الأوامر التي توافق عليها في الدردشة تُنفَّذ هنا
وتُرسَل نتيجتها للذكاء الاصطناعي.

التشغيل في Termux:
    pkg install python -y
    curl -sLO https://norestrictions-ai-chat.netlify.app/agent.py
    python agent.py مفتاح_الجهاز

في Pydroid 3: افتح الملف واضغط تشغيل، ثم الصق مفتاح الجهاز عندما يُطلب منك.
أوقفه في أي وقت بـ Ctrl+C. يحتاج Python 3 فقط (بدون مكتبات إضافية).
"""
import json, os, re, signal, ssl, subprocess, sys, time, platform, threading
import http.client
from urllib.parse import urlsplit

SERVER = os.environ.get("NR_SERVER", "https://norestrictions-ai-chat.netlify.app").rstrip("/")
KEY_FILE = os.path.join(os.path.expanduser("~"), ".nr_agent_key")
TIMEOUT = int(os.environ.get("NR_CMD_TIMEOUT", "120"))
MAX_OUT = 20000
PWD_MARK = "__NR_PWD__"
VERSION = "2"


def detect_kind():
    if os.environ.get("TERMUX_VERSION") or "com.termux" in os.environ.get("PREFIX", ""):
        return "termux"
    if "pydroid" in sys.executable.lower() or "ru.iiec.pydroid" in os.getcwd():
        return "pydroid"
    return "python"


KIND = detect_kind()


def load_key():
    key = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NR_KEY", "")).strip().lower()
    if not key and os.path.exists(KEY_FILE):
        key = open(KEY_FILE).read().strip().lower()
    while not re.fullmatch(r"[a-f0-9]{64}", key or ""):
        if key:
            print("المفتاح غير صحيح، انسخه كاملاً من نافذة «ربط الجهاز» في الموقع.")
        key = input("الصق مفتاح الجهاز: ").strip().lower()
    try:
        with open(KEY_FILE, "w") as f:
            f.write(key)
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return key


class ServerError(Exception):
    def __init__(self, code, body):
        super().__init__("HTTP %s" % code)
        self.code, self.body = code, body


# One persistent HTTPS connection per thread: avoids a new TLS handshake on every
# request, which is what made commands feel slow on mobile networks.
_U = urlsplit(SERVER)
_BASE = _U.path.rstrip("/")
_CTX = ssl.create_default_context()
_local = threading.local()


def _conn(timeout):
    c = getattr(_local, "conn", None)
    if c is None:
        if _U.scheme == "https":
            c = http.client.HTTPSConnection(_U.netloc, timeout=timeout, context=_CTX)
        else:
            c = http.client.HTTPConnection(_U.netloc, timeout=timeout)
        _local.conn = c
    c.timeout = timeout
    if c.sock is not None:
        c.sock.settimeout(timeout)
    return c


def _drop():
    c = getattr(_local, "conn", None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass
    _local.conn = None


def api(path, payload, timeout=40):
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "nr-agent/" + VERSION, "Connection": "keep-alive"}
    for attempt in range(2):
        c = _conn(timeout)
        try:
            c.request("POST", _BASE + "/api/device/" + path, body=data, headers=headers)
            r = c.getresponse()
            body = r.read().decode(errors="ignore")
        except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, http.client.CannotSendRequest):
            _drop()  # stale keep-alive connection: reconnect once
            if attempt:
                raise
            continue
        except Exception:
            _drop()
            raise
        if r.getheader("connection", "").lower() == "close":
            _drop()
        if r.status >= 400:
            raise ServerError(r.status, body[:200])
        return json.loads(body or "{}")


cwd = os.path.expanduser("~")
running = {}  # job id -> Popen
running_lock = threading.Lock()


def child_env():
    env = dict(os.environ)
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("TERM", "dumb")
    return env


def run(job_id, command):
    """Shell command by default; a first line of `#!python` runs the rest as Python."""
    global cwd
    lines = command.split("\n", 1)
    is_py = lines[0].strip().lower() in ("#!python", "#!py")
    if is_py:
        args, stdin_data, shell = [sys.executable, "-"], (lines[1] if len(lines) > 1 else ""), False
    else:
        args = command + "\n__nr_rc=$?\necho\necho " + PWD_MARK + "\"$(pwd)\"\nexit $__nr_rc\n"
        stdin_data, shell = None, True
    try:
        p = subprocess.Popen(
            args, shell=shell, cwd=cwd, env=child_env(), text=True,
            # No keyboard input: commands that ask a question get EOF instead of hanging forever.
            stdin=subprocess.PIPE if is_py else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except Exception as e:
        return "[خطأ في التنفيذ: %s]" % e, -1
    with running_lock:
        running[job_id] = p
    try:
        out, err = p.communicate(input=stdin_data, timeout=TIMEOUT)
        code = p.returncode
        if getattr(p, "nr_cancelled", False):
            return ((out or "") + (err or "") + "\n[تم إيقاف الأمر بطلب منك]").strip(), -1
    except subprocess.TimeoutExpired:
        kill(p)
        out, err = p.communicate()
        return ((out or "") + (err or "")).strip()[-MAX_OUT:] + "\n[توقف الأمر بعد %d ثانية]" % TIMEOUT, -1
    finally:
        with running_lock:
            running.pop(job_id, None)
    if not is_py:
        m = re.search(r"\n?" + PWD_MARK + r"(.*)\n?$", out)
        if m:
            if os.path.isdir(m.group(1).strip()):
                cwd = m.group(1).strip()
            out = out[: m.start()]
        out = (out.rstrip("\n") + "\n" + err).strip("\n")
    else:
        out = out + err
    return out[-MAX_OUT:] or "(لا يوجد ناتج)", code


def kill(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def setup_termux():
    """Keep Termux awake and ask once for storage permission."""
    if KIND != "termux":
        return
    try:
        subprocess.Popen(["termux-wake-lock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        print("🔒 تم تفعيل termux-wake-lock (يبقى الاتصال حتى مع إطفاء الشاشة)")
    except Exception:
        pass
    if not os.path.isdir(os.path.expanduser("~/storage")):
        try:
            subprocess.Popen(["termux-setup-storage"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            print("📂 وافق على إذن الوصول للملفات في النافذة التي ظهرت (مرة واحدة فقط)")
        except Exception:
            pass


def heartbeat(key):
    """Tell the server we're alive every few seconds and stop commands the user cancelled."""
    while True:
        try:
            res = api("ping", {"key": key}, timeout=10)
            for jid in res.get("cancel", []) or []:
                with running_lock:
                    p = running.get(jid)
                if p is not None:
                    p.nr_cancelled = True
                    kill(p)
                    print("⏹ تم إيقاف الأمر", jid)
        except Exception:
            pass
        time.sleep(4)


def handle(key, job):
    print("\n▶ تنفيذ:", job["command"])
    out, code = run(job["id"], job["command"])
    print(out[:2000])
    print("◀ رمز الخروج:", code)
    for attempt in range(6):  # don't lose a result to a brief network drop
        try:
            api("done", {"key": key, "id": job["id"], "output": out, "exitCode": code}, timeout=20)
            return
        except Exception:
            time.sleep(1 + attempt)


def main():
    key = load_key()
    info = "%s · %s · Python %s" % (KIND, platform.machine(), platform.python_version())
    print("✅ الوكيل يعمل (%s). اترك هذه النافذة مفتوحة. Ctrl+C للإيقاف." % KIND)
    print("   الخادم:", SERVER)
    setup_termux()
    threading.Thread(target=heartbeat, args=(key,), daemon=True).start()
    delay = 1
    connected = False
    while True:
        try:
            res = api("poll", {"key": key, "kind": KIND, "info": info, "wait": 20}, timeout=35)
            if not connected:
                print("🟢 متصل بالموقع")
                connected = True
            delay = 1
            for job in res.get("jobs", []):
                # Run each command in its own thread so polling (and the connection) never stalls.
                threading.Thread(target=handle, args=(key, job), daemon=True).start()
        except KeyboardInterrupt:
            raise
        except ServerError as e:
            print("خطأ من الخادم:", e.code, e.body)
            connected = False
            time.sleep(delay); delay = min(delay * 2, 4)
        except Exception as e:
            if connected:
                print("انقطع الاتصال، إعادة المحاولة…", e)
            connected = False
            time.sleep(delay); delay = min(delay * 2, 4)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        with running_lock:
            for p in list(running.values()):
                kill(p)
        print("\nتم الإيقاف.")
