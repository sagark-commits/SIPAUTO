"""Reliance Jio SIP trunk template (India Ethernet SIP)."""

from __future__ import annotations

from sipauto.models import Inventory
from sipauto.providers.base import ProviderTemplate, SipArtifacts, e164_in, strip_std_prefix


class JioProvider(ProviderTemplate):
    name = "jio"

    def requires_register(self, inv: Inventory) -> bool:
        if inv.sip.require_register is not None:
            return inv.sip.require_register
        # Jio docs usually include a register line (often without secret)
        return True

    def build(self, inv: Inventory) -> SipArtifacts:
        net = inv.network
        sip = inv.sip
        pilot = strip_std_prefix(sip.pilot)
        from_user = sip.from_user or e164_in(sip.pilot)
        expiry = sip.register_expiry or 1800
        trunk = inv.ameyo.entity_name or "jio"
        host = net.sbc_ip
        port = net.sbc_port

        # Documented form: register=>Pilot@SBC/Pilot~1800 (no password)
        if sip.password:
            register = f"register => {pilot}:{sip.password}@{host}:{port}/{pilot}~{expiry}"
        else:
            register = f"register => {pilot}@{host}/{pilot}~{expiry}"

        global_sip = "\n".join([self.codec_block(inv), register, ""])

        custom = "\n".join(
            [
                "insecure=invite,port",
                "qualify=yes",
                f"fromuser={from_user}",
                f"dtmfmode={sip.dtmf_mode}",
                "",
            ]
        )

        peer = "\n".join(
            [
                f"[{trunk}]",
                "type=friend",
                f"host={host}",
                f"port={port}",
                f"fromdomain={host}",
                f"dtmfmode={sip.dtmf_mode}",
                "nat=yes",
                "canreinvite=no",
                f"context={inv.ameyo.context_name}",
                "insecure=invite,port",
                f"fromuser={from_user}",
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
            "Jio requires Media IP host route(s) for audio — collect Media IP from provider sheet.",
            "Registry may show 'No authentication' / 'Request sent' while calls still work.",
            "For random CLI: omit fromuser/fromname and use campaign/source-phone DID (>=5 digits).",
            "Ensure ONBOOT=yes on Rocky/RHEL ifcfg for the SIP NIC.",
        ]
        if not net.media_ips:
            notes.append("WARNING: media_ips empty — expect one-way/no audio until media routes exist.")

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
                    f"fromdomain={host}",
                    f"dtmfmode={sip.dtmf_mode}",
                    "qualify=yes",
                    self.codec_block(inv),
                ]
            ),
            freepbx_register_string=f"{pilot}@{host}/{pilot}",
        )
