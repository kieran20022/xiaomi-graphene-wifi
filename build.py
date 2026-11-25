"""Build dist/GrapheneHeater.exe (run: python build.py)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import make_icon  # noqa: E402

ico = ROOT / "build" / "icon.ico"
ico.parent.mkdir(exist_ok=True)
make_icon(True, True).resize((256, 256)).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])

subprocess.check_call([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "GrapheneHeater",
    "--icon", str(ico),
    "--add-data", f"{ROOT / 'ui'};ui",
    "--add-data", f"{ROOT / 'heater' / 'spec_xiaomi.heater.ma8.json'};heater",
    str(ROOT / "app.py"),
], cwd=ROOT)
print("\nBuilt:", ROOT / "dist" / "GrapheneHeater.exe")
