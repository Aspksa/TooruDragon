from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.system.config import cores_config, version
from core.system.database import Database
from datetime import datetime, timezone


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("status", choices=("running", "stopped"))
    parser.add_argument("--core")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if not args.all and not args.core:
        parser.error("use --all or --core NAME")

    registry = cores_config().get("cores", {})
    names = list(registry) if args.all else [args.core]
    unknown = [name for name in names if name not in registry]
    if unknown:
        print(f"Unknown cores: {', '.join(unknown)}", file=sys.stderr)
        return 2

    db = Database()
    db.initialize(version())
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        for name in names:
            conn.execute(
                """
                INSERT INTO core_state(core_name, status, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(core_name) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (name, args.status, now),
            )

    print(f"Desired state: {args.status} -> {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
