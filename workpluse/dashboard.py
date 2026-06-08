"""
WorkPulse Dashboard (Terminal)  v1.1  (patched)
================================================
Patches:
  - B12 query is now ordered by timestamp ascending → missed_streak is correct
  - B13 uses google.cloud.firestore.FieldFilter when available (no warnings)
  - B6  datetime.utcnow() -> datetime.now(timezone.utc)

SETUP
  pip install firebase-admin python-dotenv rich
  python dashboard.py [days_back]
"""

import os
import datetime
from collections import defaultdict
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, firestore

try:
    from google.cloud.firestore_v1.base_query import FieldFilter  # noqa
    HAS_FIELD_FILTER = True
except Exception:
    HAS_FIELD_FILTER = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("💡 Tip: pip install rich — for a prettier dashboard")

load_dotenv()
SA_KEY_PATH = os.getenv("FIREBASE_SA_PATH", "serviceAccountKey.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(SA_KEY_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()
UTC = datetime.timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
def fetch_checkins(days_back: int = 1):
    """Fetch all check-ins from the last N days, ordered by timestamp asc."""
    since = datetime.datetime.now(UTC) - datetime.timedelta(days=days_back)
    q = db.collection("checkins")
    if HAS_FIELD_FILTER:
        q = q.where(filter=FieldFilter("timestamp", ">=", since))
    else:
        q = q.where("timestamp", ">=", since)
    q = q.order_by("timestamp")  # B12 — required for correct missed_streak
    return [d.to_dict() for d in q.stream()]


def compute_scores(checkins):
    """
    Returns per-employee stats. Assumes input is ordered by timestamp ASC.
    """
    stats = defaultdict(lambda: {
        "name": "",
        "total": 0,
        "responded": 0,
        "response_times": [],
        "missed_streak": 0,
        "last_checkin": None,
    })

    for c in checkins:
        eid = c.get("employee_id", "unknown")
        s = stats[eid]
        s["name"] = c.get("employee_name", eid)
        s["total"] += 1

        if c.get("responded"):
            s["responded"] += 1
            s["missed_streak"] = 0
            s["response_times"].append(c.get("response_time_sec", 0))
        else:
            s["missed_streak"] += 1

        ts = c.get("timestamp")
        if ts and (s["last_checkin"] is None or ts > s["last_checkin"]):
            s["last_checkin"] = ts

    for eid, s in stats.items():
        s["missed"] = s["total"] - s["responded"]
        s["presence_pct"] = round(s["responded"] / s["total"] * 100) if s["total"] else 0
        s["avg_response_sec"] = (
            round(sum(s["response_times"]) / len(s["response_times"]), 1)
            if s["response_times"] else None
        )
        if s["presence_pct"] >= 80:
            s["status"] = "🟢 Active"
        elif s["presence_pct"] >= 50:
            s["status"] = "🟡 Partial"
        else:
            s["status"] = "🔴 Inactive"
        if s["missed_streak"] >= 3:
            s["status"] = "⚠️  Alert"

    return dict(stats)


def print_dashboard(days_back: int = 1):
    print(f"\n📊 WorkPulse Report — last {days_back} day(s)\n")

    checkins = fetch_checkins(days_back)
    if not checkins:
        print("No check-in data found yet. Make sure agent.py is running!")
        return

    scores = compute_scores(checkins)

    if HAS_RICH:
        console = Console()
        table = Table(box=box.ROUNDED, header_style="bold magenta")
        table.add_column("Employee", style="cyan", min_width=14)
        table.add_column("Status", min_width=12)
        table.add_column("Presence", justify="right")
        table.add_column("Responded", justify="right")
        table.add_column("Missed", justify="right")
        table.add_column("Avg Response", justify="right")

        for eid, s in sorted(scores.items(), key=lambda x: -x[1]["presence_pct"]):
            avg = f"{s['avg_response_sec']}s" if s["avg_response_sec"] else "—"
            table.add_row(
                s["name"], s["status"],
                f"[bold]{s['presence_pct']}%[/bold]",
                str(s["responded"]), str(s["missed"]), avg,
            )
        console.print(table)
    else:
        header = f"{'Employee':<18} {'Status':<14} {'Presence':>9} {'Responded':>10} {'Missed':>7} {'AvgResp':>8}"
        print(header)
        print("─" * len(header))
        for eid, s in sorted(scores.items(), key=lambda x: -x[1]["presence_pct"]):
            avg = f"{s['avg_response_sec']}s" if s["avg_response_sec"] else "—"
            print(f"{s['name']:<18} {s['status']:<14} "
                  f"{s['presence_pct']:>8}% {s['responded']:>10} "
                  f"{s['missed']:>7} {avg:>8}")

    alerts = [s for s in scores.values() if "Alert" in s["status"]]
    if alerts:
        print(f"\n⚠️  ALERTS — {len(alerts)} employee(s) missed 3+ consecutive check-ins:")
        for s in alerts:
            print(f"   • {s['name']} — {s['missed_streak']} missed in a row")

    print(f"\n  Total check-ins in period: {len(checkins)}")
    print(f"  Report generated: {datetime.datetime.now():%Y-%m-%d %H:%M}\n")


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print_dashboard(days)
