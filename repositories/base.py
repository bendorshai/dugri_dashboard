"""
base.py — BaseRepository: לוגיקת CRUD משותפת מול קולקציה אחת.

מונע כפילות בין ה-repositories ומרכז את ההמרה dict<->model במקום אחד.

תלוי ב: pymongo, pydantic.
נצרך על ידי: כל ה-repositories הקונקרטיות.
"""

from __future__ import annotations

from typing import TypeVar, Generic

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class BaseRepository(Generic[T]):
    def __init__(self, collection, model_class: type[T]):
        self._collection = collection
        self._model_class = model_class

    def _to_model(self, doc: dict) -> T:
        return self._model_class.from_mongo_dict(doc)

    def _to_doc(self, model: T) -> dict:
        return model.to_mongo_dict()

    def get_by_id(self, doc_id) -> T | None:
        doc = self._collection.find_one({"_id": doc_id})
        if doc is None:
            return None
        return self._to_model(doc)

    def insert(self, model: T) -> T:
        doc = self._to_doc(model)
        result = self._collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return self._to_model(doc)

    def update_by_id(self, doc_id, fields: dict) -> None:
        self._collection.update_one({"_id": doc_id}, {"$set": fields})

    def delete_by_id(self, doc_id) -> None:
        self._collection.delete_one({"_id": doc_id})

    def find(self, filter_dict: dict) -> list[T]:
        docs = self._collection.find(filter_dict)
        return [self._to_model(doc) for doc in docs]

    def find_one(self, filter_dict: dict) -> T | None:
        doc = self._collection.find_one(filter_dict)
        if doc is None:
            return None
        return self._to_model(doc)
