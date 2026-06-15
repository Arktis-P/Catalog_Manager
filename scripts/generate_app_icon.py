"""Sync app icon assets from project-root appicon.png.

Source of truth: appicon.png (project root)

Outputs:
  desktop/assets/appicon.png
  desktop/assets/appicon.ico   (pywebview window / taskbar)
  frontend/public/appicon.png
  frontend/public/favicon.ico    (browser tab / app-mode window)

After changing appicon.png, run:
  scripts\\sync_app_icon.bat
"""

from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PNG_PATH = PROJECT_ROOT / "appicon.png"
PNG_TARGETS = (
    PROJECT_ROOT / "desktop" / "assets" / "appicon.png",
    PROJECT_ROOT / "frontend" / "public" / "appicon.png",
)
ICO_TARGETS = (
    PROJECT_ROOT / "desktop" / "assets" / "appicon.ico",
    PROJECT_ROOT / "frontend" / "public" / "favicon.ico",
)


def main() -> int:
    if not PNG_PATH.is_file():
        print(f"[icon] Source not found: {PNG_PATH}")
        return 1

    try:
        from PIL import Image
    except ImportError:
        print("[icon] Pillow is required. Run: pip install Pillow")
        return 1

    for target in PNG_TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PNG_PATH, target)
        print(f"[icon] Wrote {target}")

    img = Image.open(PNG_PATH).convert("RGBA")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_bytes = None
    for ico_path in ICO_TARGETS:
        ico_path.parent.mkdir(parents=True, exist_ok=True)
        if ico_bytes is None:
            img.save(ico_path, format="ICO", sizes=sizes)
            ico_bytes = ico_path.read_bytes()
        else:
            ico_path.write_bytes(ico_bytes)
        print(f"[icon] Wrote {ico_path}")

    print("[icon] Done. Restart the desktop app to see the new icon.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
