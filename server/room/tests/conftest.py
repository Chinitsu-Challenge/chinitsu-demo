"""
server/room/tests/conftest.py
pytest 配置：将 server/ 加入 Python 路径，使测试可以直接 import 服务端模块。
"""
import sys
from pathlib import Path

# 文件位于 server/room/tests/conftest.py
# parent       → server/room/tests/
# parent.parent → server/room/
# parent.parent.parent → server/          ← 这是我们需要的根路径
_server_dir = Path(__file__).resolve().parent.parent.parent

_tests_dir = Path(__file__).resolve().parent

sys.path.insert(0, str(_server_dir))   # 使 room.*, game, redis_client 等可导入
sys.path.insert(0, str(_tests_dir))    # 使 helpers.py 可以直接 import

# app.py 在导入时会挂载 assets/ 目录，确保目录存在以避免导入失败
(_server_dir / "assets").mkdir(exist_ok=True)
