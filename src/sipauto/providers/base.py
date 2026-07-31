"""Base provider template helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sipauto.models import Inventory


@dataclass
class SipArtifacts:
    register_line: str | None
    global_sip: str
    peer_chan_sip: str
    peer_pjsip: str
    custom_config: str
    hosts_entries: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    freepbx_peer_details: str = ""
    freepbx_register_string: str | None = None


def strip_std_prefix(pilot: str) -> str:
    """Strip leading country/STD style prefixes used in Indian carrier sheets."""
    p = pilot.strip().replace(" ", "")
    if p.startswith("+91"):
        p = p[3:]
    if p.startswith("91") and len(p) > 10:
        p = p[2:]
    if p.startswith("0") and len(p) > 10:
        p = p[1:]
    return p


def e164_in(pilot: str) -> str:
    p = pilot.strip().replace(" ", "")
    if p.startswith("+"):
        return p
    if p.startswith("91") and len(p) >= 12:
        return f"+{p}"
    if p.startswith("0"):
        p = p[1:]
    return f"+91{p}"


class ProviderTemplate(ABC):
    name: str

    @abstractmethod
    def build(self, inv: Inventory) -> SipArtifacts:
        raise NotImplementedError

    def requires_register(self, inv: Inventory) -> bool:
        if inv.sip.require_register is not None:
            return inv.sip.require_register
        return True

    def codec_block(self, inv: Inventory) -> str:
        lines = ["disallow=all"]
        for c in inv.sip.codecs:
            lines.append(f"allow={c}")
        return "\n".join(lines)
