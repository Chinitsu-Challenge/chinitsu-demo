import sys
from pathlib import Path

_server_dir = Path(__file__).resolve().parent
_chinitsu_dir = _server_dir.parent

# Allow `from server import app` and satisfy server.py's own internal
# bare imports (e.g. `from game import ChinitsuGame`).
sys.path.insert(0, str(_server_dir))

# server.py mounts the assets directory as a static route at import time.
# Create it if assets haven't been downloaded yet so the import doesn't fail.
(_chinitsu_dir / "assets").mkdir(exist_ok=True)
