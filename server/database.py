from pathlib import Path
import aiosqlite

DB_PATH = Path(__file__).resolve().parent.parent / "chinitsu.db"


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
