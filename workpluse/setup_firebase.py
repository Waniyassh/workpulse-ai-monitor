"""
WorkPulse Firebase Setup
========================
Run this ONCE to set up Firestore with sample data and verify your connection.

  python setup_firebase.py
"""

import datetime
import os
from dotenv import load_dotenv

load_dotenv()

import firebase_admin
from firebase_admin import credentials, firestore

print("🔧 WorkPulse Firebase Setup")
print("=" * 40)

# ── Connect ───────────────────────────────────────────────────────────────────
try:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Connected to Firebase!")
except Exception as e:
    print(f"❌ Firebase connection failed: {e}")
    print("\nMake sure serviceAccountKey.json is in this folder.")
    print("Get it from: Firebase Console → Project Settings → Service Accounts → Generate Key")
    exit(1)

# ── Create collections with sample data ──────────────────────────────────────
print("\n📝 Creating sample data...")

# Sample employee profiles
employees = [
    {
        "id":        "emp_001",
        "name":      "Alice Kumar",
        "interests": ["cricket", "technology", "cooking"],
        "department": "Engineering",
        "created_at": datetime.datetime.utcnow(),
    },
    {
        "id":        "emp_002",
        "name":      "Raj Patel",
        "interests": ["movies", "travel", "football"],
        "department": "Design",
        "created_at": datetime.datetime.utcnow(),
    },
]

for emp in employees:
    db.collection("employees").document(emp["id"]).set(emp)
    print(f"  ✅ Created employee: {emp['name']}")

# Sample check-in records (for demo)
sample_checkins = [
    {
        "employee_id":       "emp_001",
        "employee_name":     "Alice Kumar",
        "timestamp":         datetime.datetime.utcnow() - datetime.timedelta(hours=2),
        "hour":              10,
        "question":          "How many test matches has India won this year?",
        "responded":         True,
        "response_time_sec": 4.2,
        "idle_seconds":      12.0,
    },
    {
        "employee_id":       "emp_001",
        "employee_name":     "Alice Kumar",
        "timestamp":         datetime.datetime.utcnow() - datetime.timedelta(hours=1),
        "hour":              11,
        "question":          "Are you still at your desk? Click YES!",
        "responded":         False,
        "response_time_sec": 60.0,
        "idle_seconds":      450.0,
    },
    {
        "employee_id":       "emp_002",
        "employee_name":     "Raj Patel",
        "timestamp":         datetime.datetime.utcnow() - datetime.timedelta(hours=1, minutes=30),
        "hour":              10,
        "question":          "Who directed the movie 3 Idiots?",
        "responded":         True,
        "response_time_sec": 8.7,
        "idle_seconds":      22.0,
    },
]

for checkin in sample_checkins:
    db.collection("checkins").add(checkin)

print(f"  ✅ Created {len(sample_checkins)} sample check-ins")

# ── Print Firestore structure ─────────────────────────────────────────────────
print("""
📂 Firestore collections created:

  /employees/{employee_id}
    ├── id, name, interests[], department, created_at

  /checkins/{auto_id}
    ├── employee_id, employee_name
    ├── timestamp, hour
    ├── question (the popup text)
    ├── responded (true/false)
    ├── response_time_sec (how fast they clicked)
    └── idle_seconds (keyboard idle time at moment of popup)

  /sessions/{auto_id}
    ├── employee_id, employee_name
    ├── timestamp
    ├── idle_seconds
    └── active (true if idle < 5 min)
""")

print("🎉 Setup complete! Now:")
print("  1. Copy .env.example to .env and fill in your values")
print("  2. Run:  python agent.py    ← on each employee's computer")
print("  3. Run:  python dashboard.py ← to see the report")
