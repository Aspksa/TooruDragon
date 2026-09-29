from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "http://127.0.0.1:8700/cores"


def fetch_status():
    with urllib.request.urlopen(ENDPOINT, timeout=2.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload


def main() -> int:
    last_error = None

    for _ in range(10):
        try:
            status, payload = fetch_status()
            print(json.dumps(payload, ensure_ascii=False, indent=2))

            if status == 200 and payload.get("status") == "ok":
                print("[OK] All TooruDragon cores are online.")
                return 0

            last_error = f"Main Core returned HTTP {status}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)

        time.sleep(1)

    print(f"[ERROR] TooruDragon health check failed: {last_error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
