import json
import os
from datetime import datetime, timedelta

def get_training_status():
    # Try to read from heartbeat first (real bot state)
    hb_path = "/tmp/profitlab_quantum/heartbeat.json"
    try:
        if os.path.exists(hb_path):
            with open(hb_path, "r") as f:
                hb = json.load(f)
                if "training_status" in hb and hb["training_status"]:
                    ts = hb["training_status"]
                    # Ensure we have valid timestamps
                    if ts.get("next_training"):
                        return ts
    except Exception as e:
        print(f"Error: {e}")
        pass

    # Fallback
    return {"status": "fallback"}

print(get_training_status())
