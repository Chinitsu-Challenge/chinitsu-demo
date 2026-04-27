import os
from pathlib import Path
import aiosqlite

_data_env = os.environ.get("DATA_DIR", "")
_data_dir = Path(_data_env) if _data_env else Path(__file__).resolve().parent.parent
DB_PATH = _data_dir / "chinitsu.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uuid TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)
        await db.commit()


async def get_db():
    return await aiosqlite.connect(DB_PATH)
