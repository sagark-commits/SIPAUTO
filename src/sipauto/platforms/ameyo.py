"""Ameyo Call Manager artifact pack and optional write plan."""

from __future__ import annotations

from sipauto.models import Inventory
from sipauto.providers.base import SipArtifacts


def render_ameyo_pack(inv: Inventory, artifacts: SipArtifacts) -> dict[str, str]:
    """Files an engineer (or optional write) can apply for Ameyo+Asterisk."""
    entity = inv.ameyo.entity_name or inv.provider.value
    return {
        "ameyo_global_sip.conf.txt": artifacts.global_sip,
        "ameyo_call_entity_custom.conf.txt": artifacts.custom_config,
        f"asterisk_peer_{entity}.conf": artifacts.peer_chan_sip,
        f"asterisk_pjsip_{entity}.conf": artifacts.peer_pjsip,
        "ameyo_ui_checklist.md": _ui_checklist(inv, artifacts),
        "NOTES.md": "\n".join(f"- {n}" for n in artifacts.notes) + "\n",
    }


def _ui_checklist(inv: Inventory, artifacts: SipArtifacts) -> str:
    net = inv.network
    sip = inv.sip
    return f"""# Ameyo UI checklist (Call Manager)

## Voice Resource
- Voice Resource: `{inv.ameyo.voice_resource}`
- Paste **Global SIP Configuration** from `ameyo_global_sip.conf.txt`

## Call Entity / Call Context
- Entity name: `{inv.ameyo.entity_name}`
- Entity type: `DEFAULT_SIP`
- Host Name: see provider (Tata/Jio/Vi: SBC IP `{net.sbc_ip}`; Airtel: domain)
- Port: `{net.sbc_port}`
- From Domain: provider-specific (see generated peer)
- DTMF: `{sip.dtmf_mode}`
- User / Password: as in inventory
- Custom Configuration: paste `ameyo_call_entity_custom.conf.txt`
- Context: `{inv.ameyo.context_name}` — Is Local / Allow Incoming / Allow Outgoing

## Register flag
- Prefer **Register to remote party = Yes** when supported (avoids duplicate manual register lines).
- If using manual Global SIP register, remove redundant strings after save.

## Verify
```bash
asterisk -rx "sip show registry"
```
"""


def ameyo_write_plan(inv: Inventory, artifacts: SipArtifacts) -> dict[str, str]:
    """
    Optional remote write targets for Ameyo/Asterisk.

    Ameyo UI settings ultimately land in Asterisk + DB. Without a confirmed
    internal API we write include files under asterisk etc and instruct reload.
    """
    etc = inv.ameyo.asterisk_etc.rstrip("/")
    entity = inv.ameyo.entity_name or inv.provider.value
    files = {
        f"{etc}/sipauto_{entity}_peer.conf": artifacts.peer_chan_sip,
        f"{etc}/sipauto_{entity}_pjsip.conf": artifacts.peer_pjsip,
        f"{etc}/sipauto_{entity}_global_sip.snippet": artifacts.global_sip,
        f"{etc}/sipauto_rtp.snippet": (
            f"rtpstart={inv.network.rtp_start}\nrtpend={inv.network.rtp_end}\n"
        ),
    }
    return files


AMEYO_WRITE_WARNING = """
Ameyo write will:
  1. Backup existing target files (*.sipauto.bak)
  2. Write sipauto_* include snippets under Asterisk etc
  3. Ensure `#include "sipauto_*"` lines exist in sip.conf / pjsip.conf when possible
  4. Reload Asterisk SIP/PJSIP modules

It does NOT create Call Context rows in the Ameyo Admin UI/DB by itself.
Use the generated UI checklist for Call Manager fields, or supply an internal
API hook later.
""".strip()
