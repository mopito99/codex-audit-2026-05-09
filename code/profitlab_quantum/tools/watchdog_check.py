import json
import os
import sys
from datetime import datetime, timezone


def _parse_iso(ts: str) -> float:
    # returns epoch seconds
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def main() -> int:
    hb_path = os.getenv("PLQ_HEARTBEAT_PATH", "/tmp/profitlab_quantum/heartbeat.json")
    max_age_s = float(os.getenv("PLQ_MAX_AGE_SECONDS", "180"))

    if not os.path.exists(hb_path):
        print(f"CRIT: heartbeat missing: {hb_path}")
        return 2

    try:
        hb = json.loads(open(hb_path, "r").read())
    except Exception as e:
        print(f"CRIT: heartbeat unreadable: {e}")
        return 2

    ts = hb.get("ts_utc")
    if not isinstance(ts, str) or not ts:
        print("CRIT: heartbeat missing ts_utc")
        return 2

    try:
        hb_epoch = _parse_iso(ts)
    except Exception as e:
        print(f"CRIT: heartbeat ts parse failed: {e}")
        return 2

    now = datetime.now(timezone.utc).timestamp()
    age = now - hb_epoch

    if age > max_age_s:
        print(f"CRIT: heartbeat stale age={age:.1f}s > {max_age_s:.1f}s")
        return 2

    print(f"OK: heartbeat age={age:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
