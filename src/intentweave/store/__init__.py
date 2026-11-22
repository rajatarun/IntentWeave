from intentweave.store.base import ThreadStore
from intentweave.store.memory import MemoryThreadStore
from intentweave.store.sqlite import SQLiteThreadStore

__all__ = ["ThreadStore", "MemoryThreadStore", "DynamoDBThreadStore", "SQLiteThreadStore"]


def __getattr__(name: str):
    if name == "DynamoDBThreadStore":
        from intentweave.store.dynamodb import DynamoDBThreadStore

        return DynamoDBThreadStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
