#!/usr/bin/env python3
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import create_engine_from_env, init_db
from app.import_seed import import_seed_file


def main() -> None:
    seed_path = ROOT / "data" / "seed" / "xhs_generated_content.json"
    engine = create_engine_from_env()
    init_db(engine)
    result = import_seed_file(engine, seed_path)
    target = os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'citycity.db'}")
    print(f"Imported {result.imported_count}, skipped {result.skipped_count} into {target}")


if __name__ == "__main__":
    main()
