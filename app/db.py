import logging

from pymongo import MongoClient
from pymongo.collection import Collection

from app.config import MONGODB_DB_NAME, MONGODB_URI

logger = logging.getLogger(__name__)

_client: MongoClient | None = None


def connect() -> None:
    global _client
    logger.info("Connecting to MongoDB (db=%s)", MONGODB_DB_NAME)
    _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    _client.admin.command("ping")
    logger.info("MongoDB connection established")


def disconnect() -> None:
    global _client
    if _client is not None:
        logger.info("Closing MongoDB connection")
        _client.close()
        _client = None


def get_generations_collection() -> Collection:
    if _client is None:
        raise RuntimeError("MongoDB client is not connected")
    return _client[MONGODB_DB_NAME]["generation"]
