from __future__ import annotations

from pymongo import MongoClient

from shopkeeper_kb.settings import Settings, get_settings


def create_mongo_client(settings: Settings) -> MongoClient:
    return MongoClient(settings.mongo_uri)


def get_mongo_client() -> MongoClient:
    settings = get_settings()
    return create_mongo_client(settings)
