"""
WorkPulse Desktop Agent v2.1  (patched)
=======================================
Patches in v2.1:
  - B1  removed dead `shake_job` variable
  - B2  removed stray f-string prefix
  - B3  replaced blocking `time.sleep(15*60)` with non-blocking threading.Timer
  - B4  meeting-process matching is now exact (no false positives like "zoominfo")
  - B5  psutil iteration wraps NoSuchProcess / AccessDenied
  - B6  datetime.utcnow() -> datetime.now(timezone.utc) everywhere
  - B7  Calendar key warning printed at startup if key set but OAuth-required
  - B8  fixed root.bind("", ...) -> root.bind("<KeyPress>", ...) (popup now actually accepts keys)
  - B9  macOS window list uses newline delimiter (handles commas in titles)
  - B10 Linux: warns once if neither wmctrl nor xdotool available
  - B11 INTERESTS now .strip()-ed per item
  - B14 model name configurable via CLAUDE_MODEL env var
  - B16 popup adds a "Snooze 5 min" button + graceful SIGINT shutdown

SETUP
  pip install pynput firebase-admin requests python-dotenv psutil
  (Windows extra: pip install pywin32)
  Put your serviceAccountKey.json next to this file
  Fill in your .env
"""

import time
import random
import threading
import datetime
import os
import sys
import signal
import shutil
import tkinter as tk
import requests
import psutil
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

EMPLOYEE_ID    = os.getenv("EMPLOYEE_ID", "emp_001")
EMPLOYEE_NAME  = os.getenv("EMPLOYEE_NAME", "Employee")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
INTERESTS      = [i.strip() for i in os.getenv("INTERESTS", "cricket,movies,technology").split(",") if i.strip()]
GCAL_API_KEY   = os.getenv("GCAL_API_KEY", "")
GCAL_CAL_ID    = os.getenv("GCAL_CAL_ID", "primary")
SA_KEY_PATH    = os.getenv("FIREBASE_SA_PATH", "serviceAccountKey.json")

# Init Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate(SA_KEY_PATH)
    firebase_admin.initialize_app(cred)
db = firestore.client()

UTC = datetime.timezone.utc
def utcnow():
    return datetime.datetime.now(UTC)

# Calendar-key sanity warning (B7)
if GCAL_API_KEY and GCAL_CAL_ID == "primary":
    print("⚠️  GCAL_API_KEY is set but a plain API key cannot read a user's "
          "'primary' calendar — OAuth2 is required. Calendar guard will likely "
          "be a no-op. See README.")

# ─────────────────────────────────────────────────────────────────────────────
# MEETING DETECTION
# ─────────────────────────────────────────────────────────────────────────────

# Exact-match basenames (lower-case, without .exe extension)
MEETING_PROCESSES = {
    "zoom", "zoomphone",
    "teams", "ms-teams", "msteams",
    "webex", "webexmeetings", "ciscowebex",
    "slack",
    "discord",
    "skype",
    "gotomeeting", "g2mcomm",
}

MEETING_WINDOW_KEYWORDS = [
    "meet.google.com",
    "zoom.us/j/",
    "teams.microsoft.com",
    "meet - google chrome",
    "google meet",
    "microsoft teams meeting",
    "zoom meeting",
    "webex meeting",
    "on a call",
    "in a huddle",
]

# Print "no window-list tool" warning only once
_warned_no_wm = False


def _normalize_proc_name(name: str) -> str:
    n = (name or "").lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return n


def get_active_window_titles() -> list:
    """Return list of visible window titles (cross-platform, best-effort)."""
    global _warned_no_wm
    titles = []
    try:
        if sys.platform == "win32":
            import ctypes
            import ctypes.wintypes

            EnumWindows = ctypes.windll.user32.EnumWindows
            GetWindowText = ctypes.windll.user32.GetWindowTextW
            GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible

            results = []
            def foreach_window(hwnd, _):
                if IsWindowVisible(hwnd):
                    length = GetWindowTextLength(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        GetWindowText(hwnd, buf, length + 1)
                        results.append(buf.value.lower())
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
            )
            EnumWindows(WNDENUMPROC(foreach_window), 0)
            titles = results

        elif sys.platform == "darwin":
            import subprocess
            # B9: newline-delimited so commas in titles don't break parsing
            script = '''
            tell application "System Events"
                set outText to ""
                repeat with p in (every process whose visible is true)
                    repeat with w in (every window of p)
                        set outText to outText & (name of w as string) & linefeed
                    end repeat
                end repeat
                return outText
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                titles = [t.strip().lower() for t in result.stdout.splitlines() if t.strip()]

        else:
            # Linux: try wmctrl, then xdotool, else warn once
            import subprocess
            tool = None
            if shutil.which("wmctrl"):
                tool = ["wmctrl", "-l"]
            elif shutil.which("xdotool"):
                tool = ["xdotool", "search", "--name", "."]
            if tool:
                try:
                    result = subprocess.run(tool, capture_output=True, text=True, timeout=3)
                    if result.returncode == 0:
                        titles = [line.lower() for line in result.stdout.splitlines()]
                except Exception:
                    pass
            elif not _warned_no_wm:
                print("⚠️  Neither wmctrl nor xdotool is installed — browser-meeting "
                      "detection on Linux will be limited to process scan.")
                _warned_no_wm = True
    except Exception as e:
        print(f"⚠️  Window title check failed: {e}")

    return titles


def is_meeting_app_running():
    """Return (in_meeting: bool, reason: str)."""
    # 1. Processes — EXACT match (B4)
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                pname = _normalize_proc_name(proc.info.get("name"))
                if pname in MEETING_PROCESSES:
                    # B5 — Slack/Discord only count as "in call" if CPU is non-trivial
                    if pname in ("slack", "discord"):
                        try:
                            cpu = proc.cpu_percent(interval=0.2)
                            if cpu < 5:
                                continue
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    return True, f"Meeting app running: {pname}"
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        print(f"⚠️  Process scan error: {e}")

    # 2. Browser window titles
    for title in get_active_window_titles():
        for keyword in MEETING_WINDOW_KEYWORDS:
            if keyword in title:
                return True, f"Browser meeting detected: '{keyword}'"

    return False, ""


def check_google_calendar():
    """
    Returns (in_meeting, event_title). API-key path only works for *public*
    calendars; for a user's primary calendar OAuth2 is required.
    """
    if not GCAL_API_KEY:
        return False, ""
    try:
        now = utcnow()
        time_min = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (now + datetime.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"https://www.googleapis.com/calendar/v3/calendars/{GCAL_CAL_ID}/events"
        params = {
            "key": GCAL_API_KEY,
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code in (401, 403):
            # Don't spam the log — silently treat as "no calendar info"
            return False, ""
        data = resp.json()
        for event in data.get("items", []):
            title = event.get("summary", "Calendar event")
            kw = ["meeting", "call", "sync", "standup", "interview",
                  "review", "demo", "sprint", "zoom", "teams", "meet"]
            if any(k in title.lower() for k in kw):
                return True, title
            if event.get("hangoutLink") or event.get("conferenceData"):
                return True, title
    except Exception as e:
        print(f"⚠️  Calendar check failed: {e}")
    return False, ""


def is_in_meeting():
    in_mtg, reason = is_meeting_app_running()
    if in_mtg:
        return True, reason
    in_cal, event_title = check_google_calendar()
    if in_cal:
        return True, f"Calendar: {event_title}"
    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY TRACKING
# ─────────────────────────────────────────────────────────────────────────────

last_activity_time = time.time()
activity_lock = threading.Lock()

def on_activity(*args):
    global last_activity_time
    with activity_lock:
        last_activity_time = time.time()

def start_activity_monitor():
    from pynput import keyboard, mouse
    kb = keyboard.Listener(on_press=on_activity)
    mouse_ = mouse.Listener(on_move=on_activity, on_click=on_activity)
    kb.daemon = True
    mouse_.daemon = True
    kb.start()
    mouse_.start()
    print("✅ Activity monitor started")


# ─────────────────────────────────────────────────────────────────────────────
# AI QUESTION GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

FALLBACK_QUESTIONS = [
    "What year was Python created?",
    "Name one thing you are working on today.",
    "How many cups of coffee today?",
    "Quick: what is 17 x 3?",
]

def get_ai_question(interests):
    if not CLAUDE_API_KEY:
        return random.choice(FALLBACK_QUESTIONS)
    topic = random.choice(interests).strip() if interests else "general knowledge"
    prompt = (
        f"Generate ONE short fun trivia question (max 12 words) about {topic}. "
        f"Return ONLY the question, nothing else, no punctuation at start."
    )
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 60,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=8,
        )
        return resp.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"⚠️  AI question failed: {e}")
        return "Are you still at your desk? Press the key shown to confirm!"


# ─────────────────────────────────────────────────────────────────────────────
# FIREBASE LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def log_checkin(question, responded, response_time_sec, skipped_reason=""):
    now = utcnow()
    db.collection("checkins").add({
        "employee_id":       EMPLOYEE_ID,
        "employee_name":     EMPLOYEE_NAME,
        "timestamp":         now,
        "hour":              now.hour,
        "date":              now.strftime("%Y-%m-%d"),
        "question":          question,
        "responded":         responded,
        "response_time_sec": round(response_time_sec, 2),
        "idle_seconds":      round(time.time() - last_activity_time, 1),
        "skipped_reason":    skipped_reason,
        "skipped":           bool(skipped_reason),
        "interests":         INTERESTS,
    })
    status = f"skipped ({skipped_reason})" if skipped_reason else f"responded={responded}"
    print(f"📤 Logged | {status} | delay={response_time_sec:.1f}s")


def log_session_activity():
    now = utcnow()
    idle = round(time.time() - last_activity_time, 1)
    db.collection("sessions").add({
        "employee_id":   EMPLOYEE_ID,
        "employee_name": EMPLOYEE_NAME,
        "timestamp":     now,
        "date":          now.strftime("%Y-%m-%d"),
        "idle_seconds":  idle,
        "active":        idle < 300,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POPUP WINDOW — keyboard key challenge
# ─────────────────────────────────────────────────────────────────────────────

CHALLENGE_KEYS = list("ABCDEFGHJKLMNPQRSTUVWXYZ")  # no I/O — avoid confusion

def show_popup(question: str):
    """
    Returns (responded: bool, response_time_sec: float, snoozed: bool).
    Press the displayed key to confirm presence; "Snooze 5m" defers; 60s auto-close.
    """
    required_key = random.choice(CHALLENGE_KEYS)
    result = {"responded": False, "elapsed": 60.0, "wrong_presses": 0, "snoozed": False}
    popup_start = time.time()

    root = tk.Tk()
    root.title("WorkPulse Check-in")
    root.geometry("460x300")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.configure(bg="#1e1e2e")

    auto_close_job = [None]

    def close_missed():
        result["elapsed"] = 60.0
        try:
            root.destroy()
        except Exception:
            pass

    def on_correct_key():
        result["responded"] = True
        result["elapsed"] = time.time() - popup_start
        if auto_close_job[0]:
            root.after_cancel(auto_close_job[0])
        key_box.config(bg="#a6e3a1", fg="#1e1e2e")
        status_var.set("✅ Confirmed!")
        root.after(400, root.destroy)

    def on_wrong_key(pressed: str):
        result["wrong_presses"] += 1
        status_var.set(f"❌ Wrong key ({pressed}) — press {required_key}")
        x, y = root.winfo_x(), root.winfo_y()
        def shake(steps=6, dx=8):
            if steps == 0:
                root.geometry(f"+{x}+{y}")
                return
            root.geometry(f"+{x + (dx if steps % 2 == 0 else -dx)}+{y}")
            root.after(40, shake, steps - 1, dx)
        shake()
        key_box.config(bg="#f38ba8", fg="#1e1e2e")
        root.after(600, lambda: key_box.config(bg="#313244", fg="#cba6f7"))
        root.after(600, lambda: status_var.set("Press the key shown below"))

    def on_snooze():
        result["snoozed"] = True
        result["elapsed"] = time.time() - popup_start
        if auto_close_job[0]:
            root.after_cancel(auto_close_job[0])
        try:
            root.destroy()
        except Exception:
            pass

    # B8 — bind to <KeyPress>, not "" (the original bug)
    def on_key_press(event):
        pressed = (event.keysym or "").upper()
        if pressed == required_key:
            on_correct_key()
        elif len(pressed) == 1 and pressed.isalpha():
            on_wrong_key(pressed)
    root.bind("<KeyPress>", on_key_press)
    root.focus_force()

    tk.Label(root, text="⏰ WorkPulse Check-in",
             bg="#1e1e2e", fg="#cba6f7",
             font=("Helvetica", 13, "bold")).pack(pady=(16, 2))

    tk.Label(root, text=question,
             bg="#1e1e2e", fg="#cdd6f4",
             font=("Helvetica", 10), wraplength=420, justify="center").pack(pady=(0, 10))

    status_var = tk.StringVar(value="Press the key shown below")
    tk.Label(root, textvariable=status_var,
             bg="#1e1e2e", fg="#a6adc8",
             font=("Helvetica", 10)).pack()

    key_box = tk.Label(root, text=required_key,
                       bg="#313244", fg="#cba6f7",
                       font=("Helvetica", 38, "bold"),
                       width=3, relief="flat", pady=6)
    key_box.pack(pady=(8, 4))

    tk.Label(root, text=f"Press [{required_key}] on your keyboard to confirm you're here",
             bg="#1e1e2e", fg="#6c7086",
             font=("Helvetica", 9)).pack()

    # B16 — Snooze button
    snooze_btn = tk.Button(root, text="Snooze 5 min",
                           command=on_snooze,
                           bg="#45475a", fg="#cdd6f4",
                           activebackground="#585b70", activeforeground="#ffffff",
                           relief="flat", padx=10, pady=3,
                           font=("Helvetica", 9))
    snooze_btn.pack(pady=(8, 2))

    countdown_var = tk.StringVar(value="Auto-closes in 60s")
    tk.Label(root, textvariable=countdown_var,
             bg="#1e1e2e", fg="#45475a",
             font=("Helvetica", 8)).pack(pady=(4, 0))

    def tick(remaining=60):
        if remaining <= 0:
            close_missed()
            return
        countdown_var.set(f"Auto-closes in {remaining}s")
        auto_close_job[0] = root.after(1000, tick, remaining - 1)

    tick()
    root.mainloop()
    return result["responded"], result["elapsed"], result["snoozed"]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

_stop_event = threading.Event()

def get_next_delay_seconds() -> float:
    base = 60
    offset = random.randint(0, 59)
    total = (base + offset) * 60
    fire_at = datetime.datetime.now() + datetime.timedelta(seconds=total)
    print(f"   Next check-in scheduled: {fire_at:%H:%M} ({base + offset} min)")
    return total


def _schedule_retry(delay_sec: float):
    """Non-blocking retry (B3) — main loop keeps running."""
    print(f"   ⏱  Postponing check-in by {delay_sec/60:.0f} min (non-blocking)")
    t = threading.Timer(delay_sec, run_checkin)
    t.daemon = True
    t.start()


def run_checkin():
    if _stop_event.is_set():
        return
    print(f"\n   Check-in triggered at {datetime.datetime.now():%H:%M:%S}")

    in_mtg, reason = is_in_meeting()
    if in_mtg:
        print(f"   In meeting: {reason}")
        log_checkin(
            question="[skipped — meeting in progress]",
            responded=False,
            response_time_sec=0,
            skipped_reason=reason,
        )
        _schedule_retry(15 * 60)  # B3 fix
        return

    question = get_ai_question(INTERESTS)
    responded, delay, snoozed = show_popup(question)

    if snoozed:
        log_checkin(question, False, delay, skipped_reason="snoozed_by_user")
        _schedule_retry(5 * 60)
        return

    log_checkin(question, responded, delay)
    log_session_activity()
    print(f"   {'✅' if responded else '❌'} responded={responded} delay={delay:.1f}s")


def _shutdown(*_):
    print("\n👋 Shutting down WorkPulse agent...")
    _stop_event.set()
    sys.exit(0)


def main():
    print(f"""
WorkPulse Agent v2.1
  Employee          : {EMPLOYEE_NAME}
  ID                : {EMPLOYEE_ID}
  Model             : {CLAUDE_MODEL}
  Meeting detection : ON
""")
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    start_activity_monitor()
    while not _stop_event.is_set():
        delay = get_next_delay_seconds()
        # interruptible sleep
        if _stop_event.wait(delay):
            break
        run_checkin()


if __name__ == "__main__":
    main()
