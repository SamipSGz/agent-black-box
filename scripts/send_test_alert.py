"""Fire a fake SigNoz alert at the copilot so you can test the RCA path without
wiring real alerts yet.

    python scripts/send_test_alert.py retry_storm
    python scripts/send_test_alert.py bad_rag sess-1a2b3c4d
"""
from __future__ import annotations

import sys

import httpx

MODE = sys.argv[1] if len(sys.argv) > 1 else "retry_storm"
SESSION = sys.argv[2] if len(sys.argv) > 2 else "sess-demo01"
URL = "http://localhost:8099/alerts"

payload = {
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": MODE.replace("_", " ").title(),
                "failure_mode": MODE,
                "agent_session_id": SESSION,
                "trace_id": "0000000000000000abc123def456",
            },
            "annotations": {"summary": f"synthetic {MODE} alert for testing"},
        }
    ]
}

resp = httpx.post(URL, json=payload, timeout=30)
print(resp.status_code, resp.json())
print("\nOpen http://localhost:8099/ to see the rendered report.")
