"""Parse pasted carrier delivery sheet / email text into inventory fields."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sipauto.models import (
    AmeyoConfig,
    Inventory,
    NetworkConfig,
    Platform,
    Provider,
    SipConfig,
    SipDriver,
    Site,
)

IP = r"(?:\d{1,3}\.){3}\d{1,3}"
MASK = r"(?:\d{1,3}\.){3}\d{1,3}"


@dataclass
class CarrierSheetParse:
    provider: Optional[Provider] = None
    customer_ip: Optional[str] = None
    gateway_ip: Optional[str] = None
    sbc_ip: Optional[str] = None
    sbc_port: int = 5060
    netmask: Optional[str] = None
    media_ips: list[str] = field(default_factory=list)
    pilot: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    domain: Optional[str] = None
    vlan_id: Optional[int] = None
    did_start: Optional[str] = None
    did_end: Optional[str] = None
    dids: list[str] = field(default_factory=list)
    channels: Optional[int] = None
    raw_hits: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def missing_required(self) -> list[str]:
        need = ["customer_ip", "gateway_ip", "sbc_ip", "pilot"]
        return [k for k in need if not getattr(self, k)]

    def to_inventory_dict(
        self,
        *,
        site_name: str,
        interface: str = "eth1",
        platform: Platform = Platform.AMEYO_ASTERISK,
        provider: Optional[Provider] = None,
    ) -> dict[str, Any]:
        prov = provider or self.provider or Provider.TATA
        netmask = self.netmask or "255.255.255.252"
        pilot = self.pilot or "0000000000"
        sip: dict[str, Any] = {
            "pilot": pilot,
            "password": self.password,
            "username": self.username,
            "domain": self.domain,
            "dids": self.dids,
            "did_start": self.did_start,
            "did_end": self.did_end,
        }
        if prov == Provider.JIO:
            sip["register_expiry"] = 1800
        if prov == Provider.AIRTEL:
            sip["domain"] = self.domain or "ims.airtel.in"
            sip["register_expiry"] = 1800
        if prov == Provider.VODAFONE:
            sip["require_register"] = bool(self.password)

        data: dict[str, Any] = {
            "site": {"name": site_name, "mode": "onprem"},
            "provider": prov.value,
            "platform": platform.value,
            "sip_driver": (
                SipDriver.PJSIP.value
                if platform == Platform.FREEPBX
                else SipDriver.CHAN_SIP.value
            ),
            "network": {
                "interface": interface,
                "customer_ip": self.customer_ip or "0.0.0.0",
                "gateway_ip": self.gateway_ip or "0.0.0.0",
                "sbc_ip": self.sbc_ip or "0.0.0.0",
                "sbc_port": self.sbc_port,
                "netmask": netmask,
                "media_ips": self.media_ips,
                "vlan_id": self.vlan_id,
                "sip_transport": "both",
                "rtp_start": 10000,
                "rtp_end": 40000,
            },
            "sip": sip,
            "ameyo": {
                "entity_name": prov.value,
                "context_name": f"{prov.value}-ctx",
            },
        }
        return data

    def to_inventory(
        self,
        *,
        site_name: str,
        interface: str = "eth1",
        platform: Platform = Platform.AMEYO_ASTERISK,
        provider: Optional[Provider] = None,
    ) -> Inventory:
        return Inventory.model_validate(
            self.to_inventory_dict(
                site_name=site_name,
                interface=interface,
                platform=platform,
                provider=provider,
            )
        )


def _first(patterns: list[str], text: str, flags: int = re.I) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            return m.group(1).strip()
    return None


def _all_ips_after(label_pat: str, text: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(label_pat, text, re.I | re.M):
        # capture rest of line and following indented lines lightly
        chunk = text[m.end() : m.end() + 300]
        found.extend(re.findall(IP, chunk))
    # dedupe preserve order
    out: list[str] = []
    for ip in found:
        if ip not in out:
            out.append(ip)
    return out


def detect_provider(text: str) -> Optional[Provider]:
    t = text.lower()
    scores = {
        Provider.TATA: len(re.findall(r"\btata\b|tata communications|tatasip", t)),
        Provider.JIO: len(re.findall(r"\bjio\b|reliance jio", t)),
        Provider.AIRTEL: len(re.findall(r"\bairtel\b|ims\.airtel\.in", t)),
        Provider.VODAFONE: len(
            re.findall(r"\bvodafone\b|\bvi\b|vodafone.?idea|vodafone-idea", t)
        ),
    }
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else None


def parse_carrier_sheet(text: str, *, hint_provider: Optional[Provider] = None) -> CarrierSheetParse:
    """Extract fields from free-form carrier provisioning text."""
    result = CarrierSheetParse()
    result.provider = hint_provider or detect_provider(text)

    result.customer_ip = _first(
        [
            rf"Customer\s*IP\s*[:=]\s*({IP})",
            rf"Customer\s*I\.?P\.?\s*[:=]\s*({IP})",
            rf"Server\s*IP\s*[:=]\s*({IP})",
            rf"LAN\s*IP\s*[:=]\s*({IP})",
            rf"PBX\s*IP\s*[:=]\s*({IP})",
        ],
        text,
    )
    result.gateway_ip = _first(
        [
            rf"Gateway\s*IP\s*[:=]\s*({IP})",
            rf"Gateway\s*[:=]\s*({IP})",
            rf"GW\s*[:=]\s*({IP})",
            rf"Default\s*Gateway\s*[:=]\s*({IP})",
        ],
        text,
    )
    result.sbc_ip = _first(
        [
            rf"SBC\s*IP\s*[:=]\s*({IP})",
            rf"SIP\s*Server\s*IP\s*[:=]\s*({IP})",
            rf"SIP\s*Server\s*[:=]\s*({IP})",
            rf"SIP\s*Gateway\s*IP\s*[:=]\s*({IP})",
            rf"Proxy\s*[:=]\s*({IP})",
            rf"Registrar\s*[:=]\s*({IP})",
        ],
        text,
    )
    port = _first(
        [
            r"(?:SBC|SIP|Destination)\s*Port\s*[:=]\s*(\d{2,5})",
            r"Port\s*[:=]\s*(5060|5061|\d{4,5})",
        ],
        text,
    )
    if port:
        result.sbc_port = int(port)

    result.netmask = _first(
        [
            rf"(?:Subnet\s*Mask|Net-?Mask|Netmask|Subnet)\s*[:=]\s*({MASK})",
            rf"PREFIX\s*[:=]\s*(\d{{1,2}})",
        ],
        text,
    )
    if result.netmask and result.netmask.isdigit():
        # PREFIX style — convert common ones
        prefix = int(result.netmask)
        result.netmask = {
            30: "255.255.255.252",
            29: "255.255.255.248",
            28: "255.255.255.240",
            24: "255.255.255.0",
        }.get(prefix, "255.255.255.252")
        result.raw_hits["prefix"] = str(prefix)

    media = _all_ips_after(
        r"Media\s*IP(?:s)?\s*[:=]",
        text,
    )
    # Also "Media IP 10.x" inline lists
    media += re.findall(rf"Media(?:\s*IP)?[^\d]*({IP})", text, re.I)
    # Drop IPs already used as customer/gw/sbc
    reserved = {result.customer_ip, result.gateway_ip, result.sbc_ip}
    result.media_ips = [ip for ip in dict.fromkeys(media) if ip not in reserved]

    result.pilot = _first(
        [
            r"Pilot\s*(?:No\.?|Number|DID)?\s*[:=]\s*(\+?\d[\d\s-]{6,})",
            r"Hunt\s*(?:No\.?|Number)?\s*[:=]\s*(\+?\d[\d\s-]{6,})",
            r"Primary\s*(?:No\.?|Number|DID)\s*[:=]\s*(\+?\d[\d\s-]{6,})",
        ],
        text,
    )
    if result.pilot:
        result.pilot = re.sub(r"[\s-]", "", result.pilot)

    did_range = re.search(
        r"DID\s*Range\s*[:=]\s*(\+?\d[\d\s-]*)\s*(?:to|-|–)\s*(\+?\d[\d\s-]*)",
        text,
        re.I,
    )
    if did_range:
        result.did_start = re.sub(r"[\s-]", "", did_range.group(1))
        result.did_end = re.sub(r"[\s-]", "", did_range.group(2))
        if not result.pilot:
            result.pilot = result.did_start

    result.username = _first(
        [
            r"User\s*Name\s*[:=]\s*(\S+)",
            r"Username\s*[:=]\s*(\S+)",
            r"Auth\s*User\s*[:=]\s*(\S+)",
        ],
        text,
    )
    result.password = _first(
        [
            r"Password\s*[:=]\s*(\S+)",
            r"Secret\s*[:=]\s*(\S+)",
            r"Pass(?:wd)?\s*[:=]\s*(\S+)",
        ],
        text,
    )
    result.domain = _first(
        [
            r"(ims\.airtel\.in|[a-z]{2}\.ims\.airtel\.in)",
            r"Domain\s*[:=]\s*(\S+)",
            r"From\s*Domain\s*[:=]\s*(\S+)",
            r"SIP\s*Domain\s*[:=]\s*(\S+)",
        ],
        text,
    )
    vlan = _first([r"VLAN(?:\s*/\s*port|\s*ID|\s*Tag)?\s*[:=]\s*(\d+)"], text)
    if vlan:
        result.vlan_id = int(vlan)
    ch = _first([r"Channels?\s*[:=]\s*(\d+)"], text)
    if ch:
        result.channels = int(ch)

    # Confidence score
    fields = [
        result.customer_ip,
        result.gateway_ip,
        result.sbc_ip,
        result.pilot,
        result.netmask,
    ]
    hit = sum(1 for f in fields if f)
    result.confidence = hit / len(fields)
    if result.provider:
        result.confidence = min(1.0, result.confidence + 0.1)
    if result.media_ips:
        result.confidence = min(1.0, result.confidence + 0.05)

    for key in ("customer_ip", "gateway_ip", "sbc_ip", "pilot", "password", "domain"):
        val = getattr(result, key)
        if val:
            result.raw_hits[key] = str(val)

    missing = result.missing_required()
    if missing:
        result.warnings.append(f"Missing required fields: {', '.join(missing)}")
    if result.provider in (Provider.JIO, Provider.AIRTEL, Provider.VODAFONE) and not result.media_ips:
        result.warnings.append("No Media IP(s) found — audio may fail until media routes exist")
    if result.provider == Provider.AIRTEL and not result.password:
        result.warnings.append("Airtel usually requires a password")
    if result.provider == Provider.AIRTEL and not result.domain:
        result.domain = "ims.airtel.in"
        result.warnings.append("Airtel domain defaulted to ims.airtel.in")

    return result
