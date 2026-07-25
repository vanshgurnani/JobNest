import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DB", "job_portal")

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
from app.schemas.job import canonicalize_job

PROD_URI = os.getenv("PROD_MONGO_URI", "mongodb://localhost:27017")
PROD_DB = os.getenv("PROD_MONGO_DB", "job_intelligence")


async def migrate():
    src_settings = get_settings()
    src_client = AsyncIOMotorClient(src_settings.mongodb_uri)
    src_coll = src_client[src_settings.mongodb_db]["jobs"]

    tgt_client = AsyncIOMotorClient(PROD_URI)
    tgt_coll = tgt_client[PROD_DB]["jobs"]

    total = await src_coll.count_documents({})
    print(f"Source: {src_settings.mongodb_uri}/{src_settings.mongodb_db}  ({total} jobs)")
    print(f"Target: {PROD_URI}/{PROD_DB}")

    cursor = src_coll.find({})
    inserted = 0
    skipped = 0
    batch: list[dict] = []
    async for doc in cursor:
        doc.pop("_id", None)
        job = canonicalize_job(doc)
        batch.append(job)
        if len(batch) >= 100:
            for j in batch:
                await tgt_coll.update_one({"id": j["id"]}, {"$set": j}, upsert=True)
            inserted += len(batch)
            print(f"  Migrated {inserted}/{total}...")
            batch = []

    if batch:
        for j in batch:
            await tgt_coll.update_one({"id": j["id"]}, {"$set": j}, upsert=True)
        inserted += len(batch)

    src_client.close()
    tgt_client.close()
    print(f"Done. {inserted} jobs migrated, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(migrate())
