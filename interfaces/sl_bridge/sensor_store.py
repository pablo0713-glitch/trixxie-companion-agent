from __future__ import annotations

from typing import Any


class SensorStore:
    """
    In-memory cache of the latest sensor snapshots from Trixxie's HUD.
    Keyed by region name — sensor data describes the environment, not the user.

    Sensor types and their storage behaviour:
      avatars      → latest snapshot (list of {name, distance})
      environment  → latest snapshot ({region, parcel, time_of_day, ...})
      objects      → latest snapshot (list of {name, distance, scripted})
      clothing     → latest scan result ({target, items: [...]})
      chat         → rolling list of notable events (last max_chat_events entries)
    """

    def __init__(self, max_chat_events: int = 10) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._max_chat = max_chat_events

    def update(self, region: str, sensor_type: str, data: Any) -> None:
        if region not in self._store:
            self._store[region] = {}
        if sensor_type == "chat":
            events: list = self._store[region].get("chat_events", [])
            events.append(data)
            if len(events) > self._max_chat:
                events = events[-self._max_chat:]
            self._store[region]["chat_events"] = events
        else:
            self._store[region][sensor_type] = data

    def get_snapshot(self, region: str) -> dict[str, Any]:
        """Return a copy of all sensor data for the given region."""
        return dict(self._store.get(region, {}))
