"""Inventory and shared models — stdlib dataclasses (no pydantic)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import Any, Optional


class Provider(str, Enum):
    TATA = "tata"
    JIO = "jio"
    AIRTEL = "airtel"
    VODAFONE = "vodafone"


class Platform(str, Enum):
    AMEYO_ASTERISK = "ameyo_asterisk"
    FREEPBX = "freepbx"
    ASTERISK = "asterisk"


class DeployMode(str, Enum):
    ONPREM = "onprem"
    CLOUD = "cloud"
    SHARED = "shared"


class SipDriver(str, Enum):
    CHAN_SIP = "chan_sip"
    PJSIP = "pjsip"


def _enum(cls, value, default=None):
    if value is None:
        return default
    if isinstance(value, cls):
        return value
    return cls(value)


@dataclass
class Site:
    name: str
    mode: DeployMode = DeployMode.ONPREM

    @classmethod
    def from_dict(cls, d: dict) -> "Site":
        return cls(name=d["name"], mode=_enum(DeployMode, d.get("mode"), DeployMode.ONPREM))


@dataclass
class NetworkConfig:
    interface: str
    customer_ip: str
    gateway_ip: str
    sbc_ip: str
    sbc_port: int = 5060
    netmask: str = "255.255.255.252"
    prefix: Optional[int] = None
    vlan_id: Optional[int] = None
    media_ips: list[str] = field(default_factory=list)
    sip_transport: str = "udp"
    rtp_start: int = 10000
    rtp_end: int = 40000

    @classmethod
    def from_dict(cls, d: dict) -> "NetworkConfig":
        for key in ("customer_ip", "gateway_ip", "sbc_ip"):
            if not str(d.get(key, "")).strip():
                raise ValueError(f"{key} is required")
        return cls(
            interface=str(d.get("interface") or "eth1"),
            customer_ip=str(d["customer_ip"]).strip(),
            gateway_ip=str(d["gateway_ip"]).strip(),
            sbc_ip=str(d["sbc_ip"]).strip(),
            sbc_port=int(d.get("sbc_port") or 5060),
            netmask=str(d.get("netmask") or "255.255.255.252"),
            prefix=d.get("prefix"),
            vlan_id=d.get("vlan_id"),
            media_ips=list(d.get("media_ips") or []),
            sip_transport=str(d.get("sip_transport") or "udp"),
            rtp_start=int(d.get("rtp_start") or 10000),
            rtp_end=int(d.get("rtp_end") or 40000),
        )


@dataclass
class SipConfig:
    pilot: str
    password: Optional[str] = None
    username: Optional[str] = None
    auth_user: Optional[str] = None
    domain: Optional[str] = None
    from_user: Optional[str] = None
    from_name: Optional[str] = None
    codecs: list[str] = field(default_factory=lambda: ["alaw", "ulaw", "g729"])
    register_expiry: int = 300
    dtmf_mode: str = "rfc2833"
    require_register: Optional[bool] = None
    dids: list[str] = field(default_factory=list)
    did_start: Optional[str] = None
    did_end: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "SipConfig":
        return cls(
            pilot=str(d["pilot"]),
            password=d.get("password"),
            username=d.get("username"),
            auth_user=d.get("auth_user"),
            domain=d.get("domain"),
            from_user=d.get("from_user"),
            from_name=d.get("from_name"),
            codecs=list(d.get("codecs") or ["alaw", "ulaw", "g729"]),
            register_expiry=int(d.get("register_expiry") or 300),
            dtmf_mode=str(d.get("dtmf_mode") or "rfc2833"),
            require_register=d.get("require_register"),
            dids=list(d.get("dids") or []),
            did_start=d.get("did_start"),
            did_end=d.get("did_end"),
        )


@dataclass
class AmeyoConfig:
    voice_resource: str = "DefaultVR"
    entity_name: Optional[str] = None
    context_name: Optional[str] = None
    asterisk_etc: str = "/etc/asterisk"
    global_sip_snippet_path: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "AmeyoConfig":
        d = d or {}
        return cls(
            voice_resource=str(d.get("voice_resource") or "DefaultVR"),
            entity_name=d.get("entity_name"),
            context_name=d.get("context_name"),
            asterisk_etc=str(d.get("asterisk_etc") or "/etc/asterisk"),
            global_sip_snippet_path=d.get("global_sip_snippet_path"),
        )


@dataclass
class FreePBXConfig:
    trunk_name: Optional[str] = None
    asterisk_etc: str = "/etc/asterisk"
    use_pjsip: bool = True

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "FreePBXConfig":
        d = d or {}
        return cls(
            trunk_name=d.get("trunk_name"),
            asterisk_etc=str(d.get("asterisk_etc") or "/etc/asterisk"),
            use_pjsip=bool(d["use_pjsip"]) if "use_pjsip" in d else True,
        )


@dataclass
class SSHConfig:
    host: str
    user: str = "root"
    port: int = 22
    key_path: Optional[str] = None
    password: Optional[str] = None
    connect_timeout: int = 15

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional["SSHConfig"]:
        if not d:
            return None
        return cls(
            host=str(d["host"]).strip(),
            user=str(d.get("user") or "root"),
            port=int(d.get("port") or 22),
            key_path=d.get("key_path"),
            password=d.get("password"),
            connect_timeout=int(d.get("connect_timeout") or 15),
        )


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return {f.name: _to_plain(getattr(obj, f.name)) for f in fields(obj)}
    return obj


@dataclass
class Inventory:
    site: Site
    provider: Provider
    network: NetworkConfig
    sip: SipConfig
    platform: Platform = Platform.AMEYO_ASTERISK
    sip_driver: SipDriver = SipDriver.CHAN_SIP
    ameyo: AmeyoConfig = field(default_factory=AmeyoConfig)
    freepbx: FreePBXConfig = field(default_factory=FreePBXConfig)
    ssh: Optional[SSHConfig] = None

    def __post_init__(self) -> None:
        if not self.ameyo.entity_name:
            self.ameyo.entity_name = self.provider.value
        if not self.ameyo.context_name:
            self.ameyo.context_name = f"{self.provider.value}-ctx"
        if not self.freepbx.trunk_name:
            self.freepbx.trunk_name = f"{self.provider.value}siptrunk"

    @classmethod
    def model_validate(cls, data: dict) -> "Inventory":
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Inventory":
        inv = cls(
            site=Site.from_dict(data["site"]),
            provider=_enum(Provider, data["provider"]),
            platform=_enum(Platform, data.get("platform"), Platform.AMEYO_ASTERISK),
            sip_driver=_enum(SipDriver, data.get("sip_driver"), SipDriver.CHAN_SIP),
            network=NetworkConfig.from_dict(data["network"]),
            sip=SipConfig.from_dict(data["sip"]),
            ameyo=AmeyoConfig.from_dict(data.get("ameyo")),
            freepbx=FreePBXConfig.from_dict(data.get("freepbx")),
            ssh=SSHConfig.from_dict(data.get("ssh")),
        )
        return inv

    def model_dump(self, mode: str = "python") -> dict:
        return _to_plain(self)

    def model_dump_json(self, indent: int = 2) -> str:
        return json.dumps(self.model_dump(), indent=indent)


@dataclass
class GeneratedArtifact:
    path: str
    content: str
    description: str


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    severity: str = "error"


@dataclass
class RunReport:
    site: str
    provider: str
    platform: str
    confidence: str
    checks: list[CheckResult] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        return _to_plain(self)

    def model_dump_json(self, indent: int = 2) -> str:
        return json.dumps(self.model_dump(), indent=indent)
