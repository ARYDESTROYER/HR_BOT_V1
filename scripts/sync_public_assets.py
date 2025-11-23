#!/usr/bin/env python3
"""
Copy brand assets from src/hr_bot/ui/assets/ into the public/ directory so Chainlit serves them.
Run this script during development or deployment to ensure the public assets are up-to-date.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "src" / "hr_bot" / "ui" / "assets"
PUBLIC_DIR = ROOT / "public"
AVATARS_DIR = PUBLIC_DIR / "avatars"

def ensure_public_dirs():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)

def copy_asset(src_name: str, dest_name: str | None = None):
    dest_name = dest_name or src_name
    src = ASSETS_DIR / src_name
    if not src.exists():
        print(f"Asset '{src_name}' not found in {ASSETS_DIR}")
        return
    dest = PUBLIC_DIR / dest_name
    shutil.copy2(src, dest)
    print(f"Copied {src} -> {dest}")

def copy_avatar(src_name: str, dest_name: str | None = None):
    dest_name = dest_name or src_name
    src = ASSETS_DIR / src_name
    if not src.exists():
        print(f"Avatar asset '{src_name}' not found in {ASSETS_DIR}")
        return
    dest = AVATARS_DIR / dest_name
    shutil.copy2(src, dest)
    print(f"Copied {src} -> {dest}")

def main():
    ensure_public_dirs()
    # Main header logo (full light variant)
    copy_asset("logo_full_light.png", "logo_full_light.png")
    # Keep the original logo_*.png images updated for backward compatibility
    copy_asset("logo_full_light.png", "logo_light.png")
    copy_asset("logo_full_dark.png", "logo_dark.png")
    # Default avatar (light mascot)
    copy_avatar("logo_mascot_light.png", "inara.png")
    # Keep dark variant in avatars too
    copy_avatar("logo_mascot_dark.png", "inara_dark.png")

if __name__ == "__main__":
    main()
