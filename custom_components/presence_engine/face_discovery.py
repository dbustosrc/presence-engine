"""Face catalogue metadata is not evidence of presence or identity association."""

from __future__ import annotations


class FaceDiscovery:
    def __init__(self, limit: int = 2_000) -> None:
        self.limit = limit
        self.catalogue: list[str] = []
        self.observed: dict[str, str] = {}

    def observe(self, name: str, identity: str) -> bool:
        if self.observed.get(name) == identity:
            return False
        if name not in self.observed and len(self.observed) >= self.limit:
            return False
        self.observed[name] = identity
        return True

    def update_catalogue(self, payload: object) -> None:
        if not isinstance(payload, dict) or any(
            not isinstance(name, str) or not name.strip()
            or not isinstance(images, list) or any(not isinstance(image, str) for image in images)
            for name, images in payload.items()
        ):
            raise ValueError("Invalid face catalogue")
        self.catalogue = sorted(payload)[:self.limit]

    def export(self) -> dict:
        return {"catalogue": self.catalogue, "observed": dict(self.observed)}

    def restore(self, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        catalogue = raw.get("catalogue", [])
        if isinstance(catalogue, list):
            self.catalogue = [name for name in catalogue if isinstance(name, str) and name.strip()][:self.limit]
        observed = raw.get("observed", {})
        if isinstance(observed, dict):
            self.observed = {
                name: identity for name, identity in list(observed.items())[:self.limit]
                if isinstance(name, str) and name.strip() and isinstance(identity, str) and identity.strip()
            }
