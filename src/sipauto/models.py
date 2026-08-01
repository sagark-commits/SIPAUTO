"""Inventory and shared models for SIPAUTO."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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


class Site(BaseModel):
    name: str
    mode: DeployMode = DeployMode.ONPREM


class NetworkConfig(BaseModel):
    interface: str
    customer_ip: str
    gateway_ip: str
    sbc_ip: str
    sbc_port: int = 5060
    netmask: str = "255.255.255.252"
    prefix: Optional[int] = None
    vlan_id: Optional[int] = None
    media_ips: list[str] = Field(default_factory=list)
    sip_transport: str = "udp"  # udp | tcp | both
    rtp_start: int = 10000
    rtp_end: int = 40000

    @field_validator("customer_ip", "gateway_ip", "sbc_ip")
    @classmethod
    def non_empty_ip(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("IP address is required")
        return v.strip()


class SipConfig(BaseModel):
    pilot: str
    password: Optional[str] = None
    username: Optional[str] = None
    auth_user: Optional[str] = None
    domain: Optional[str] = None
    from_user: Optional[str] = None
    from_name: Optional[str] = None
    codecs: list[str] = Field(default_factory=lambda: ["alaw", "ulaw", "g729"])
    register_expiry: int = 300
    dtmf_mode: str = "rfc2833"
    require_register: Optional[bool] = None  # provider default if None
    dids: list[str] = Field(default_factory=list)
    did_start: Optional[str] = None
    did_end: Optional[str] = None


class AmeyoConfig(BaseModel):
    voice_resource: str = "DefaultVR"
    entity_name: Optional[str] = None
    context_name: Optional[str] = None
    # Where Ameyo/Asterisk configs live on the call server
    asterisk_etc: str = "/etc/asterisk"
    global_sip_snippet_path: Optional[str] = None


class FreePBXConfig(BaseModel):
    trunk_name: Optional[str] = None
    asterisk_etc: str = "/etc/asterisk"
    use_pjsip: bool = True


class SSHConfig(BaseModel):
    host: str
    user: str = "root"
    port: int = 22
    key_path: Optional[str] = None
    password: Optional[str] = None
    connect_timeout: int = 15


class Inventory(BaseModel):
    site: Site
    provider: Provider
    platform: Platform = Platform.AMEYO_ASTERISK
    sip_driver: SipDriver = SipDriver.CHAN_SIP
    network: NetworkConfig
    sip: SipConfig
    ameyo: AmeyoConfig = Field(default_factory=AmeyoConfig)
    freepbx: FreePBXConfig = Field(default_factory=FreePBXConfig)
    ssh: Optional[SSHConfig] = None

    @model_validator(mode="after")
    def defaults(self) -> "Inventory":
        if not self.ameyo.entity_name:
            self.ameyo.entity_name = self.provider.value
        if not self.ameyo.context_name:
            self.ameyo.context_name = f"{self.provider.value}-ctx"
        if not self.freepbx.trunk_name:
            self.freepbx.trunk_name = f"{self.provider.value}siptrunk"
        # FreePBX defaults to PJSIP unless overridden
        if self.platform == Platform.FREEPBX and self.sip_driver == SipDriver.CHAN_SIP:
            # keep explicit inventory value; FreePBX adapter can still emit chan_sip
            pass
        return self


class GeneratedArtifact(BaseModel):
    path: str
    content: str
    description: str


class CheckResult(BaseModel):
    name: str
    ok: bool
    detail: str
    severity: str = "error"  # error | warn | info


class RunReport(BaseModel):
    site: str
    provider: str
    platform: str
    confidence: str  # GREEN | YELLOW | RED
    checks: list[CheckResult] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
