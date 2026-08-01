"""Tata Communications SIP trunk template (India Ethernet SIP)."""

from __future__ import annotations

from sipauto.models import Inventory
from sipauto.providers.base import ProviderTemplate, SipArtifacts, strip_std_prefix


class TataProvider(ProviderTemplate):
    name = "tata"

    def build(self, inv: Inventory) -> SipArtifacts:
        net = inv.network
        sip = inv.sip
        user = sip.username or strip_std_prefix(sip.pilot)
        password = sip.password or "1234"
        auth_user = sip.auth_user or user
        from_user = sip.from_user or user
        from_name = sip.from_name or from_user
        expiry = sip.register_expiry or 300
        host = net.sbc_ip
        port = net.sbc_port
        trunk = inv.ameyo.entity_name or "tata"

        # Prefer authuser form (fixes 407 Proxy Authentication Required)
        register = (
            f"register => {user}:{password}:{auth_user}@{host}:{port}/{user}"
            if port != 5060
            else f"register => {user}:{password}:{auth_user}@{host}/{user}"
        )
        # Simpler form also documented; keep authuser as primary
        if sip.auth_user is None and password == "1234":
            # Common documented simple form when authuser == user
            register = (
                f"register => {user}:{password}@{host}:{port}/{user}"
                if port != 5060
                else f"register => {user}:{password}@{host}/{user}"
            )

        global_sip = "\n".join(
            [
                self.codec_block(inv),
                register,
                f"defaultexpiry={expiry}",
                "",
            ]
        )

        ppi = f"P-Preferred-Identity: <sip:{from_user}@{net.customer_ip}>"
        custom = "\n".join(
            [
                "insecure=invite,port",
                f"fromuser={from_user}",
                f"fromname={from_name}",
                f"setvar=SIPADDHEADER01={ppi}",
                "qualify=yes",
                "canreinvite=no",
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
                f"dtmfmode={sip.dtmf_mode}",
                "nat=yes",
                "canreinvite=no",
                f"context={inv.ameyo.context_name}",
                "insecure=invite,port",
                f"fromuser={from_user}",
                f"fromname={from_name}",
                f"fromdomain=SIP-{user}",
                f"setvar=SIPADDHEADER={ppi}",
                self.codec_block(inv),
                "",
            ]
        )

        pjsip = _tata_pjsip(inv, user, password, from_user, trunk)

        notes = [
            "Tata often needs dedicated NIC + host route to SBC (and media IPs if no audio).",
            "If outbound 403: try removing register string and reload (see Tata GKB).",
            "If 407: use username:password:authuser@host/ext register form.",
            "If 480 after 407 fix: PPI must use Customer IP.",
            "Check NIC/mux speed (100 vs 1000) and duplex with carrier if link is down.",
        ]

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
                    f"username={user}",
                    f"secret={password}",
                    "insecure=invite,port",
                    f"fromuser={from_user}",
                    f"fromdomain={host}",
                    f"dtmfmode={sip.dtmf_mode}",
                    "qualify=yes",
                    "canreinvite=no",
                    self.codec_block(inv).replace("\n", "\n"),
                ]
            ),
            freepbx_register_string=f"{user}:{password}@{host}:{port}/{user}",
        )


def _tata_pjsip(inv: Inventory, user: str, password: str, from_user: str, trunk: str) -> str:
    net = inv.network
    return "\n".join(
        [
            f"[{trunk}]",
            "type=registration",
            "retry_interval=20",
            "max_retries=10",
            f"contact_user={user}",
            f"expiration={inv.sip.register_expiry}",
            "transport=transport-udp",
            f"outbound_auth={trunk}",
            f"client_uri=sip:{user}@{net.sbc_ip}:{net.sbc_port}",
            f"server_uri=sip:{net.sbc_ip}:{net.sbc_port}",
            "",
            f"[{trunk}]",
            "type=auth",
            "auth_type=userpass",
            f"password={password}",
            f"username={user}",
            "",
            f"[{trunk}]",
            "type=aor",
            "qualify_frequency=60",
            f"contact=sip:{user}@{net.sbc_ip}:{net.sbc_port}",
            f"default_expiration={inv.sip.register_expiry}",
            "",
            f"[{trunk}]",
            "type=identify",
            f"endpoint={trunk}",
            f"match={net.sbc_ip}",
            "",
            f"[{trunk}]",
            "type=endpoint",
            "transport=transport-udp",
            f"context={inv.ameyo.context_name}",
            f"dtmf_mode={inv.sip.dtmf_mode}",
            "disallow=all",
            *[f"allow={c}" for c in inv.sip.codecs],
            "direct_media=no",
            "rtp_symmetric=yes",
            "rewrite_contact=yes",
            f"from_user={from_user}",
            f"aors={trunk}",
            f"outbound_auth={trunk}",
            "",
        ]
    )
