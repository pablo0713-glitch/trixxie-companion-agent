from __future__ import annotations

import json
import os
from typing import Optional


class PersonMap:
    """
    Maps canonical person IDs to all their platform-specific user_ids.

    The source of truth is data/person_map.json:
        {
          "pablorios": [
            "discord_1090657639781912677",
            "sl_0f2a4fb8-efc6-4bf7-9dc5-87f99d5ce8b0"
          ]
        }

    A PersonMap with no entries is valid — it just means no cross-platform
    linking is configured yet.
    """

    def __init__(self, data: dict[str, list[str]]) -> None:
        self._by_person: dict[str, list[str]] = data
        # Reverse index: user_id → person_id
        self._by_user: dict[str, str] = {}
        for person_id, user_ids in data.items():
            for uid in user_ids:
                self._by_user[uid] = person_id

    @classmethod
    def load(cls, path: str) -> "PersonMap":
        if not os.path.exists(path):
            return cls({})
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def get_person_id(self, user_id: str) -> Optional[str]:
        """Return the canonical person name for a platform user_id, or None."""
        return self._by_user.get(user_id)

    def get_linked_ids(self, user_id: str) -> list[str]:
        """All user_ids for the same person, excluding the given one."""
        person_id = self._by_user.get(user_id)
        if person_id is None:
            return []
        return [uid for uid in self._by_person[person_id] if uid != user_id]

    def get_person_user_ids(self, person_id: str) -> list[str]:
        """All user_ids linked to a person."""
        return list(self._by_person.get(person_id, []))

    def all_persons(self) -> list[str]:
        return list(self._by_person.keys())
