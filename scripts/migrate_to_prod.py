"""
Usage:
    # Copy between two Atlas clusters (or local → Atlas)
    python scripts/migrate_to_prod.py

Environment variables:
    SOURCE_MONGO_URI   — source MongoDB connection string (default: MONGODB_URI)
    SOURCE_MONGO_DB    — source database name (default: MONGODB_DB)
    TARGET_MONGO_URI   — target MongoDB connection string
    TARGET_MONGO_DB    — target database name
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient
from app.schemas.job import canonicalize_job

SOURCE_URI = os.getenv("SOURCE_MONGO_URI") or os.getenv("MONGODB_URI", "")
SOURCE_DB = os.getenv("SOURCE_MONGO_DB") or os.getenv("MONGODB_DB", "job_portal")
TARGET_URI = os.getenv("TARGET_MONGO_URI") or os.getenv("PROD_MONGO_URI", "")
TARGET_DB = os.getenv("TARGET_MONGO_DB") or os.getenv("PROD_MONGO_DB", "job_intelligence")


async def migrate():
    if not SOURCE_URI:
        raise SystemExit("Set SOURCE_MONGO_URI (or MONGODB_URI) env var.")
    if not TARGET_URI:
        raise SystemExit("Set TARGET_MONGO_URI (or PROD_MONGO_URI) env var.")

    src_client = AsyncIOMotorClient(SOURCE_URI, serverSelectionTimeoutMS=10000)
    tgt_client = AsyncIOMotorClient(TARGET_URI, serverSelectionTimeoutMS=10000)

    await src_client.admin.command("ping")
    await tgt_client.admin.command("ping")

    src_coll = src_client[SOURCE_DB]["jobs"]
    tgt_coll = tgt_client[TARGET_DB]["jobs"]

    total = await src_coll.count_documents({})
    print(f"Source: {total} jobs from {SOURCE_DB}")
    print(f"Target: {TARGET_DB}")

    cursor = src_coll.find({})
    inserted = 0
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
    print(f"Done. {inserted} jobs migrated.")


if __name__ == "__main__":
    asyncio.run(migrate())
