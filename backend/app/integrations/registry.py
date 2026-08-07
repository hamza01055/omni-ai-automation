"""Adapter selection.

One rule: if the channel has real credentials, use the real adapter; otherwise
fall back to the mock and mark the channel as sandbox. Callers never construct
adapters directly, so there is exactly one place where "are we live?" is decided.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.integrations.base import ChannelAdapter
from app.integrations.facebook.adapter import FacebookAdapter
from app.integrations.instagram.adapter import InstagramAdapter
from app.integrations.mock import MockAdapter
from app.integrations.whatsapp.adapter import WhatsAppAdapter
from app.integrations.x.adapter import XAdapter
from app.models.enums import Platform

log = get_logger("integrations.registry")

_REAL_ADAPTERS: dict[Platform, type[ChannelAdapter]] = {
    Platform.WHATSAPP: WhatsAppAdapter,
    Platform.INSTAGRAM: InstagramAdapter,
    Platform.FACEBOOK: FacebookAdapter,
    Platform.X: XAdapter,
}


def get_adapter(platform: Platform, *, force_mock: bool = False) -> ChannelAdapter:
    if force_mock:
        return MockAdapter(platform)

    adapter = _REAL_ADAPTERS[platform]()
    if not adapter.is_live:
        log.info("adapter_falling_back_to_mock", platform=platform.value)
        return MockAdapter(platform)
    return adapter


def channel_status() -> list[dict[str, object]]:
    """What the Settings > Channels page reads to show connection state."""
    rows = []
    for platform, cls in _REAL_ADAPTERS.items():
        adapter = cls()
        rows.append({
            "platform": platform.value,
            "connected": adapter.is_live,
            "mode": "live" if adapter.is_live else "sandbox",
            "capabilities": adapter.capabilities,
        })
    return rows
