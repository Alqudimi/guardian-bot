import asyncio

from sqlalchemy import text

from src.db.session import close_db, db_session, init_db
from src.utils.redis_client import close_redis, get_redis


async def main() -> None:
    await init_db()
    async with db_session() as session:
        result = await session.execute(text("select current_database(), current_user"))
        print(f"postgres_identity={result.one()}")

    redis = await get_redis()
    await redis.set("guardian:round22:smoke", "ready", ex=30)
    print(f"redis_roundtrip={await redis.get('guardian:round22:smoke')}")
    await close_redis()
    await close_db()


asyncio.run(main())
