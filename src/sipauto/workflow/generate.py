"""Generate config artifacts from inventory + provider templates."""

from __future__ import annotations

import json
from pathlib import Path

from sipauto.models import GeneratedArtifact, Inventory, Platform
from sipauto.network.rhel import render_hosts_snippet, render_ifcfg, render_route_file
from sipauto.platforms.ameyo import render_ameyo_pack
from sipauto.platforms.asterisk import render_rtp_conf_snippet
from sipauto.platforms.freepbx import render_freepbx_pack
from sipauto.providers import get_provider


def generate(inv: Inventory, out_dir: str | Path) -> list[GeneratedArtifact]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    provider = get_provider(inv)
    artifacts = provider.build(inv)

    files: dict[str, tuple[str, str]] = {}
    # path -> (content, description)

    files["network/ifcfg"] = (render_ifcfg(inv), "Rocky/RHEL ifcfg for SIP NIC")
    files["network/route"] = (render_route_file(inv), "Host routes for SBC + media IPs")
    files["network/hosts.snippet"] = (
        render_hosts_snippet(artifacts),
        "Optional /etc/hosts entries",
    )
    files["asterisk/rtp.conf.snippet"] = (
        render_rtp_conf_snippet(inv),
        "RTP UDP range 10000-40000 (or inventory override)",
    )

    if inv.platform in (Platform.AMEYO_ASTERISK, Platform.ASTERISK):
        for name, content in render_ameyo_pack(inv, artifacts).items():
            files[f"ameyo/{name}"] = (content, f"Ameyo/Asterisk: {name}")

    if inv.platform == Platform.FREEPBX:
        for name, content in render_freepbx_pack(inv, artifacts).items():
            files[f"freepbx/{name}"] = (content, f"FreePBX: {name}")

    # Always also emit asterisk peers for dual-platform sites
    if inv.platform == Platform.FREEPBX:
        files["ameyo/ameyo_global_sip.conf.txt"] = (
            artifacts.global_sip,
            "Also useful if dual-stacking with Ameyo",
        )

    meta = {
        "site": inv.site.name,
        "provider": inv.provider.value,
        "platform": inv.platform.value,
        "sip_driver": inv.sip_driver.value,
        "sbc": f"{inv.network.sbc_ip}:{inv.network.sbc_port}",
        "rtp": f"{inv.network.rtp_start}-{inv.network.rtp_end}/udp",
        "register": artifacts.register_line,
        "notes": artifacts.notes,
    }
    files["MANIFEST.json"] = (json.dumps(meta, indent=2) + "\n", "Generation manifest")

    result: list[GeneratedArtifact] = []
    for rel, (content, desc) in files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        result.append(GeneratedArtifact(path=str(path), content=content, description=desc))
    return result
