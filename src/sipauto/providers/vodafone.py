"""Vodafone-Idea (Vi) India SIP trunk template.

Public India guides describe dedicated Ethernet + IP-auth / PJSIP identify
(often no REGISTER). Optional register/password supported when the circuit
requires digest auth.
"""

from __future__ import annotations

from sipauto.models import Inventory
from sipauto.providers.base import ProviderTemplate, SipArtifacts, e164_in, strip_std_prefix


class VodafoneProvider(ProviderTemplate):
    name = "vodafone"

    def requires_register(self, inv: Inventory) -> bool:
        if inv.sip.require_register is not None:
            return inv.sip.require_register
        # Vi India managed PJSIP commonly IP-auth — no register by default
        return bool(inv.sip.password)

    def build(self, inv: Inventory) -> SipArtifacts:
        net = inv.network
        sip = inv.sip
        pilot = strip_std_prefix(sip.pilot)
        from_user = sip.from_user or e164_in(sip.pilot)
        trunk = inv.ameyo.entity_name or "vodafone"
        host = net.sbc_ip
        port = net.sbc_port

        register = None
        if self.requires_register(inv):
            password = sip.password or ""
            user = sip.username or pilot
            register = f"register => {user}:{password}@{host}:{port}/{user}"

        global_lines = [self.codec_block(inv)]
        if register:
            global_lines.append(register)
        else:
            global_lines.append(
                f"; Vodafone-Idea: IP-auth trunk — no register (SBC {host})"
            )
        global_sip = "\n".join(global_lines) + "\n"

        custom = "\n".join(
            [
                "insecure=invite,port",
                "qualify=yes",
                f"fromuser={from_user}",
                f"dtmfmode={sip.dtmf_mode}",
                "canreinvite=no",
                "",
            ]
        )

        peer = "\n".join(
            [
                f"[{trunk}]",
                "type=peer",
                f"host={host}",
                f"port={port}",
                f"context={inv.ameyo.context_name}",
                "insecure=invite,port",
                f"fromuser={from_user}",
                f"dtmfmode={sip.dtmf_mode}",
                "directmedia=no",
                "qualify=yes",
                self.codec_block(inv),
                "",
            ]
        )

        pjsip = "\n".join(
            [
                f"[{trunk}]",
                "type=aor",
                "qualify_frequency=60",
                f"contact=sip:{trunk}@{host}:{port}",
                "",
                f"[{trunk}]",
                "type=endpoint",
                "transport=transport-udp",
                f"context={inv.ameyo.context_name}",
                "disallow=all",
                *[f"allow={c}" for c in inv.sip.codecs],
                f"aors={trunk}",
                "direct_media=no",
                "rtp_symmetric=yes",
                f"dtmf_mode={sip.dtmf_mode}",
                f"from_user={from_user}",
                "",
                f"[{trunk}]",
                "type=identify",
                f"endpoint={trunk}",
                f"match={host}",
                "",
            ]
        )

        notes = [
            "Vodafone-Idea India: typically dedicated subnet + dual NIC (same L3 model as Tata/Jio).",
            "Public guides: often NO registration string — IP-auth via identify/match on SBC IP.",
            "Collect SIP gateway IP & Media IP from Vi sheet; add media_ips for audio.",
            "This template targets Vi India Ethernet SIP — not German Vodafone Anlagen-Anschluss.",
            "Confidence medium: no internal Vi runbook in the supplied PDF set; based on public guides.",
        ]
        if not net.media_ips:
            notes.append("WARNING: media_ips empty — add Vi Media IP routes for two-way audio.")

        return SipArtifacts(
            register_line=register,
            global_sip=global_sip,
            peer_chan_sip=peer,
            peer_pjsip=pjsip,
            custom_config=custom,
            notes=notes,
            freepbx_peer_details="\n".join(
                [
                    f"host={host}",
                    f"port={port}",
                    "type=peer",
                    "insecure=invite,port",
                    f"fromuser={from_user}",
                    f"dtmfmode={sip.dtmf_mode}",
                    "qualify=yes",
                    "canreinvite=no",
                    self.codec_block(inv),
                ]
            ),
            freepbx_register_string=register.split("register => ", 1)[-1] if register else None,
        )
