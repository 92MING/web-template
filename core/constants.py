from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_DIR / "app"
RESOURCES_DIR = PROJECT_DIR / "resources"
CONFIG_DIR = PROJECT_DIR / "config"
TMP_DIR = PROJECT_DIR / "tmp"
PUBLIC_DIR = PROJECT_DIR / "public"

__all__ = [
    "PROJECT_DIR",
    "APP_DIR",
    "RESOURCES_DIR",
    "CONFIG_DIR",
    "TMP_DIR",
    "PUBLIC_DIR",
]
