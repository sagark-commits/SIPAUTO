"""Host / IP validation helpers."""

from __future__ import annotations

import ipaddress
import re


_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def is_valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value.strip())
        return True
    except ValueError:
        return False


def is_valid_host(value: str) -> bool:
    """True for IPv4 or simple DNS hostname (rejects 10.192.168.56.10 etc.)."""
    v = (value or "").strip()
    if not v:
        return False
    if is_valid_ipv4(v):
        return True
    # reject numeric-looking invalid IPs with >4 octets
    if re.fullmatch(r"[\d.]+", v):
        return False
    return bool(_HOSTNAME_RE.match(v))


def validate_host_or_raise(value: str, label: str = "host") -> str:
    v = (value or "").strip()
    if not is_valid_host(v):
        raise ValueError(
            f"Invalid {label}: {value!r}. Use IPv4 like 192.168.56.10 "
            f"(not 10.192.168.56.10) or a hostname."
        )
    return v


def validate_ssh_host(value: str) -> tuple[bool, str]:
    """Return (ok, reason) for wizard prompts."""
    v = (value or "").strip()
    if not v:
        return False, "host is empty"
    if is_valid_host(v):
        return True, ""
    if re.fullmatch(r"[\d.]+", v):
        return False, f"{v!r} is not a valid IPv4 (too many/few octets)"
    return False, f"{v!r} is not a valid IPv4 or hostname"


def looks_like_local_call_server() -> bool:
    from pathlib import Path

    return Path("/etc/asterisk").exists() or Path("/usr/lib64/asterisk").exists()
