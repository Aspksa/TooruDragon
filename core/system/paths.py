from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
SYSTEM_CONFIG_PATH = CONFIG_DIR / "system.json"
CORES_CONFIG_PATH = CONFIG_DIR / "cores.json"
SCHEMA_PATH = DATA_DIR / "schema.sql"
DB_PATH = DATA_DIR / "toorudragon.db"
