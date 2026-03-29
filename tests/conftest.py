import sys
from pathlib import Path

_project_dir = Path(__file__).resolve().parent.parent
_server_dir = _project_dir / "server"

# Allow `from app import app` and satisfy app.py's own internal
# bare imports (e.g. `from game import ChinitsuGame`).
sys.path.insert(0, str(_server_dir))

# app.py mounts the assets directory as a static route at import time.
# Create it if assets haven't been downloaded yet so the import doesn't fail.
(_server_dir / "assets").mkdir(exist_ok=True)
