import os
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from database import get_db

SECRET_KEY = os.environ.get("SECRET_KEY", "chinitsu-showdown-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_uuid: str, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_uuid, "username": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    """Decode JWT and return {"uuid": ..., "username": ...} or None."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_uuid = payload.get("sub")
        username = payload.get("username")
        if user_uuid is None or username is None:
            return None
        return {"uuid": user_uuid, "username": username}
    except JWTError:
        return None


async def register_user(username: str, password: str) -> dict:
    """Register a new user. Returns {"uuid", "username", "access_token"} or raises ValueError."""
    db = await get_db()
    try:
        # Check if username already exists
        cursor = await db.execute("SELECT uuid FROM users WHERE username = ?", (username,))
        if await cursor.fetchone():
            raise ValueError("Username already exists")

        user_uuid = str(_uuid.uuid4())
        hashed = hash_password(password)
        await db.execute(
            "INSERT INTO users (uuid, username, password) VALUES (?, ?, ?)",
            (user_uuid, username, hashed),
        )
        await db.commit()

        token = create_access_token(user_uuid, username)
        return {"uuid": user_uuid, "username": username, "access_token": token}
    finally:
        await db.close()


async def authenticate_user(username: str, password: str) -> dict:
    """Authenticate user. Returns {"uuid", "username", "access_token"} or raises ValueError."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT uuid, username, password FROM users WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("Invalid username or password")

        user_uuid, db_username, hashed = row
        if not verify_password(password, hashed):
            raise ValueError("Invalid username or password")

        token = create_access_token(user_uuid, db_username)
        return {"uuid": user_uuid, "username": db_username, "access_token": token}
    finally:
        await db.close()
