"""A stateful fake SABnzbd for respx: items move through queue -> history as tests direct."""

from __future__ import annotations

import itertools
import re

import httpx

SAB_URL = "http://sab.local:8080/api"
SAB_KEY = "SABKEY"


class FakeSab:
    def __init__(self) -> None:
        self.queue: dict[str, dict] = {}
        self.history: dict[str, dict] = {}
        self.added: list[dict] = []
        self._ids = itertools.count(1)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        mode = params.get("mode")
        if mode == "version":
            return httpx.Response(200, json={"version": "5.1.3"})
        if params.get("apikey") != SAB_KEY:
            return httpx.Response(200, json={"status": False, "error": "API Key Incorrect"})
        if mode == "get_cats":
            return httpx.Response(200, json={"categories": ["*", "magazines"]})
        if mode == "addfile":
            nzo = f"SABnzbd_nzo_{next(self._ids)}"
            name = re.search(rb'filename="([^"]+)"', request.content)
            self.added.append(
                {
                    "nzo_id": nzo,
                    "cat": params.get("cat"),
                    "file": name[1].decode() if name else None,
                }
            )
            self.queue[nzo] = {
                "nzo_id": nzo,
                "filename": params.get("nzbname"),
                "status": "Queued",
                "mb": "40",
                "mbleft": "40",
            }
            return httpx.Response(200, json={"status": True, "nzo_ids": [nzo]})
        if mode == "queue":
            return httpx.Response(
                200, json={"queue": {"paused": False, "slots": list(self.queue.values())}}
            )
        if mode == "history":
            return httpx.Response(200, json={"history": {"slots": list(self.history.values())}})
        return httpx.Response(400)

    def progress(self, nzo: str, left_mb: int) -> None:
        self.queue[nzo].update(status="Downloading", mbleft=str(left_mb))

    def complete(self, nzo: str, storage: str) -> None:
        slot = self.queue.pop(nzo)
        self.history[nzo] = {
            "nzo_id": nzo,
            "name": slot["filename"],
            "status": "Completed",
            "bytes": 40 * 1048576,
            "storage": storage,
        }

    def fail(self, nzo: str, message: str) -> None:
        slot = self.queue.pop(nzo)
        self.history[nzo] = {
            "nzo_id": nzo,
            "name": slot["filename"],
            "status": "Failed",
            "bytes": 0,
            "fail_message": message,
        }

    def forget(self, nzo: str) -> None:
        self.queue.pop(nzo, None)
        self.history.pop(nzo, None)
