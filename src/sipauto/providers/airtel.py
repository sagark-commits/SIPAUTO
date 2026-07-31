"""Airtel SIP trunk template (India IMS / Ethernet SIP)."""

from __future__ import annotations

from sipauto.models import Inventory
from sipauto.providers.base import ProviderTemplate, SipArtifacts, e164_in


class AirtelProvider(ProviderTemplate):
    name = "airtel"

    def build(self, inv: Inventory) -> SipArtifacts:
        net = inv.network
        sip = inv.sip
        domain = sip.domain or "ims.airtel.in"
        user = sip.username or e164_in(sip.pilot)
        # Airtel username is often +91...@ims.airtel.in
        if "@" not in user:
            user = f"{user}@{domain}"
        password = sip.password
        if not password:
            raise ValueError("Airtel requires sip.password in inventory")
        pilot = e164_in(sip.pilot)
        from_user = sip.from_user or pilot
        from_name = sip.from_name or from_user
        expiry = sip.register_expiry or 1800
        trunk = inv.ameyo.entity_name or "airtel"
        host_ip = net.sbc_ip
        port = net.sbc_port

        # Format from Ameyo docs:
        # register => +91...@ims.airtel.in:pass:+91...@ims.airtel.in@SBC_IP/+91...[~1800]
        register = (
            f"register => {user}:{password}:{user}@{host_ip}/{pilot}~{expiry}"
        )

        global_sip = "\n".join(
            [
                "bindport=5060",
                "bindaddr=0.0.0.0",
                "allowguest=no",
                "srvlookup=yes",
                self.codec_block(inv),
                register,
                "",
            ]
        )

        ppi = f"P-Preferred-Identity: <sip:{from_user}@{domain}>"
        custom = "\n".join(
            [
                "insecure=invite,port",
                f"fromuser={from_user}",
                f"fromname={from_name}",
                f"setvar=SIPADDHEADER01={ppi}",
                "transport=UDP",
                "qualify=yes",
                f"dtmfmode={sip.dtmf_mode}",
                "",
            ]
        )

        peer = "\n".join(
            [
                f"[{trunk}]",
                "type=friend",
                f"host={domain}",
                f"port={port}",
                f"fromdomain={domain}",
                f"username={user}",
                f"secret={password}",
                "nat=force_rport,comedia",
                "canreinvite=no",
                f"context={inv.ameyo.context_name}",
                "insecure=invite,port",
                f"fromuser={from_user}",
                f"fromname={from_name}",
                f"setvar=SIPADDHEADER01={ppi}",
                "transport=udp",
                "qualify=yes",
                self.codec_block(inv),
                "",
            ]
        )

        pjsip = "\n".join(
            [
                f"[{trunk}]",
                "type=registration",
                f"outbound_auth={trunk}",
                f"server_uri=sip:{domain}:{port}",
                f"client_uri=sip:{user}",
                f"retry_interval=60",
                f"expiration={expiry}",
                "",
                f"[{trunk}]",
                "type=auth",
                "auth_type=userpass",
                f"username={user}",
                f"password={password}",
                "",
                f"[{trunk}]",
                "type=aor",
                f"contact=sip:{domain}:{port}",
                "qualify_frequency=60",
                "",
                f"[{trunk}]",
                "type=identify",
                f"endpoint={trunk}",
                f"match={host_ip}",
                "",
                f"[{trunk}]",
                "type=endpoint",
                "transport=transport-udp",
                f"context={inv.ameyo.context_name}",
                "disallow=all",
                *[f"allow={c}" for c in inv.sip.codecs],
                f"aors={trunk}",
                f"outbound_auth={trunk}",
                f"from_user={from_user}",
                f"from_domain={domain}",
                "direct_media=no",
                "rtp_symmetric=yes",
                f"dtmf_mode={sip.dtmf_mode}",
                "",
            ]
        )

        notes = [
            "Airtel requires /etc/hosts: <SBC_IP> ims.airtel.in (or regional FQDN).",
            "Regional domains exist (e.g. mh.ims.airtel.in, ap.ims.airtel.in) — set sip.domain if needed.",
            "Many media IPs are often required for two-way audio — populate network.media_ips.",
            "If inbound fails on Ameyo entity: try removing username/password on the entity.",
            "Outbound CLI must be a valid Airtel DID (campaign Caller ID).",
        ]
        if not net.media_ips:
            notes.append("WARNING: media_ips empty — Airtel commonly needs a media IP list for audio.")

        return SipArtifacts(
            register_line=register,
            global_sip=global_sip,
            peer_chan_sip=peer,
            peer_pjsip=pjsip,
            custom_config=custom,
            hosts_entries=[f"{host_ip} {domain}"],
            notes=notes,
            freepbx_peer_details="\n".join(
                [
                    f"host={domain}",
                    f"port={port}",
                    "type=friend",
                    f"username={user}",
                    f"secret={password}",
                    f"fromdomain={domain}",
                    f"fromuser={from_user}",
                    "insecure=invite,port",
                    "nat=force_rport,comedia",
                    f"dtmfmode={sip.dtmf_mode}",
                    "qualify=yes",
                    "canreinvite=no",
                    self.codec_block(inv),
                ]
            ),
            freepbx_register_string=f"{user}:{password}:{user}@{host_ip}/{pilot}",
        )
