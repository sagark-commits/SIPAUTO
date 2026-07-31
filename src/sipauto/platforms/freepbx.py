"""FreePBX artifact pack (PJSIP preferred, chan_sip optional)."""

from __future__ import annotations

from sipauto.models import Inventory, SipDriver
from sipauto.providers.base import SipArtifacts


def render_freepbx_pack(inv: Inventory, artifacts: SipArtifacts) -> dict[str, str]:
    trunk = inv.freepbx.trunk_name or f"{inv.provider.value}siptrunk"
    use_pjsip = inv.freepbx.use_pjsip or inv.sip_driver == SipDriver.PJSIP

    pack = {
        "freepbx_trunk_guide.md": _guide(inv, artifacts, trunk, use_pjsip),
        "NOTES.md": "\n".join(f"- {n}" for n in artifacts.notes) + "\n",
    }
    if use_pjsip:
        pack[f"pjsip_{trunk}.conf"] = artifacts.peer_pjsip
    else:
        pack[f"sip_{trunk}.conf"] = artifacts.peer_chan_sip
        if artifacts.freepbx_register_string:
            pack["freepbx_register_string.txt"] = artifacts.freepbx_register_string + "\n"
        pack["freepbx_peer_details.txt"] = artifacts.freepbx_peer_details + "\n"
    return pack


def _guide(inv: Inventory, artifacts: SipArtifacts, trunk: str, use_pjsip: bool) -> str:
    net = inv.network
    return f"""# FreePBX trunk guide — {trunk}

## Connectivity → Trunks → Add Trunk
- Type: {"PJSIP" if use_pjsip else "chan_sip (legacy)"}
- Trunk name: `{trunk}`
- SIP Server / Host: `{net.sbc_ip}` (Airtel may use domain — see generated files)
- Port: `{net.sbc_port}`
- Codecs: {", ".join(inv.sip.codecs)}
- DTMF: `{inv.sip.dtmf_mode}`

## Registration
{"- Registration usually required — see freepbx_register_string.txt" if artifacts.freepbx_register_string else "- IP-auth / no registration (typical Vi/Jio PJSIP identify)"}

## Identify / Match
- Match provider SBC IP: `{net.sbc_ip}`
- Also match media IPs if inbound comes from them: {", ".join(net.media_ips) or "(none listed)"}

## After save
- Apply Config in FreePBX UI
- Or CLI reload via SIPAUTO `apply` / `reload`

## RTP
- Asterisk `rtp.conf`: rtpstart={net.rtp_start} rtpend={net.rtp_end}
- Firewall both sides: UDP {net.rtp_start}-{net.rtp_end}
"""
