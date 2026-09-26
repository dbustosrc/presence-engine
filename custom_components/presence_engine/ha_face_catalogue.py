"""Read Frigate's catalogue on demand, never on a periodic schedule."""

from __future__ import annotations

import json

from aiohttp import ClientTimeout, DummyCookieJar
from homeassistant.helpers.aiohttp_client import async_create_clientsession


async def fetch_face_catalogue(hass, settings: dict) -> object:
    async with async_create_clientsession(hass, cookie_jar=DummyCookieJar()) as session:
        return await _fetch(session, settings)


async def _fetch(session, settings):
    base = settings["url"].rstrip("/")
    if not base.endswith("/api"):
        base += "/api"
    headers = {}
    timeout = ClientTimeout(total=10)
    if settings.get("username"):
        async with session.post(
            f"{base}/login", json={"user": settings["username"], "password": settings["password"]},
            timeout=timeout, allow_redirects=False,
        ) as response:
            response.raise_for_status()
            cookie = response.cookies.get(settings.get("cookie_name", "frigate_token"))
            if cookie is None:
                raise ValueError("Frigate did not return an authentication cookie")
            headers["Authorization"] = f"Bearer {cookie.value}"
    async with session.get(f"{base}/faces", headers=headers, timeout=timeout, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status != 200:
            raise ValueError("Unexpected catalogue response")
        content = bytearray()
        async for chunk in response.content.iter_chunked(65_536):
            content.extend(chunk)
            if len(content) > 1_048_576:
                raise ValueError("Face catalogue exceeds metadata limit")
        return json.loads(content)
