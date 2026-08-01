"""Guided SIP setup wizard — stdlib prompts; SSH failures never abort the run."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from sipauto.models import (
    Inventory,
    NetworkConfig,
    Platform,
    Provider,
    SipConfig,
    SipDriver,
    Site,
    SSHConfig,
)
from sipauto.network.interfaces import choose_interface
from sipauto.parser.carrier_sheet import parse_carrier_sheet
from sipauto.ssh import SSHClient, SSHError
from sipauto.util.console import Panel, ask_choice, ask_text, ask_yes_no, console, print_table
from sipauto.util.netcheck import looks_like_local_call_server, validate_ssh_host
from sipauto.workflow.generate import generate
from sipauto.workflow.inventory_io import write_inventory
from sipauto.workflow.preflight import run_preflight
from sipauto.workflow.verify import verify


def _print_report(title: str, report) -> None:
    rows = [[c.name, "yes" if c.ok else "no", c.severity, c.detail[:120]] for c in report.checks]
    print_table(f"{title} — {report.confidence}", ["Check", "OK", "Severity", "Detail"], rows)
    if report.next_actions:
        console.print("Next actions")
        for a in report.next_actions:
            console.print(f"  • {a}")


def _prompt_ssh(existing: Optional[SSHConfig], *, yes: bool) -> Optional[SSHConfig]:
    if yes:
        return existing
    if looks_like_local_call_server():
        console.print(
            Panel(
                "This host looks like a call server (/etc/asterisk present).\n"
                "Prefer LOCAL mode (no SSH) unless you are driving a remote box.",
                title="Local call server detected",
            )
        )
    if not ask_yes_no("Configure SSH for remote preflight/apply/registry?", default=False):
        return None

    host = ask_text("SSH host (IPv4 or hostname)", default=existing.host if existing else "")
    ok, reason = validate_ssh_host(host)
    while not ok:
        console.print(f"[red]Invalid SSH host: {reason}[/red]")
        host = ask_text("SSH host (IPv4 or hostname)", default="")
        ok, reason = validate_ssh_host(host)

    user = ask_text("SSH user", default=(existing.user if existing else "root") or "root")
    port_s = ask_text("SSH port", default=str(existing.port if existing else 22))
    try:
        port = int(port_s)
    except ValueError:
        port = 22

    console.print(
        Panel(
            "Auth options:\n"
            "  • Leave key path blank to use ssh-agent / default ~/.ssh keys\n"
            "  • Or enter a path to a private key file (e.g. /root/.ssh/id_rsa)\n"
            "  • Or choose password auth (needs sshpass on this machine)",
            title="SSH authentication",
        )
    )
    key = ask_text("SSH private key path (blank = agent/default keys)", default="")
    password = None
    key_path = None
    if key.strip():
        key_path = key.strip()
        if not Path(key_path).expanduser().exists():
            console.print(f"[yellow]Key file not found: {key_path} — clearing[/yellow]")
            key_path = None
    elif ask_yes_no("Use password auth (requires sshpass)?", default=False):
        import getpass

        password = getpass.getpass("SSH password: ")

    return SSHConfig(
        host=host.strip(),
        user=user.strip() or "root",
        port=port,
        key_path=key_path,
        password=password,
    )


def _try_ssh(ssh: SSHConfig) -> Optional[SSHConfig]:
    okh, reason = validate_ssh_host(ssh.host)
    if not okh:
        console.print(f"[red]SSH host invalid ({reason}). Switching to LOCAL mode.[/red]")
        return None
    try:
        with SSHClient(ssh) as client:
            r = client.run("echo ok", check=False)
        if r.exit_code != 0 or "ok" not in (r.stdout or ""):
            console.print(
                f"[yellow]SSH login failed ({(r.stderr or r.stdout or 'auth').strip()[:200]}). "
                "Continuing in LOCAL mode.[/yellow]"
            )
            return None
        console.print(f"[green]SSH OK → {ssh.user}@{ssh.host}[/green]")
        return ssh
    except SSHError as e:
        console.print(f"[yellow]SSH unavailable ({e}). Continuing in LOCAL mode.[/yellow]")
        return None
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]SSH unavailable ({e}). Continuing in LOCAL mode.[/yellow]")
        return None


def run_wizard(
    *,
    out_root: Path,
    sheet_file: Optional[Path] = None,
    inventory_out: Optional[Path] = None,
    provider: Optional[Union[str, Provider]] = None,
    platform: Union[str, Platform] = "ameyo_asterisk",
    site: Optional[str] = None,
    site_name: Optional[str] = None,
    iface: Optional[str] = None,
    interface: Optional[str] = None,
    yes: bool = False,
    non_interactive: bool = False,
    skip_apply: bool = True,
) -> Path:
    yes = yes or non_interactive
    iface = iface or interface
    site = site or site_name

    console.print(Panel("Step 1/6 — Choose carrier provider", title="SIPAUTO wizard"))
    prov_map = {
        "1": "tata",
        "2": "jio",
        "3": "airtel",
        "4": "vodafone",
        "tata": "tata",
        "jio": "jio",
        "airtel": "airtel",
        "vodafone": "vodafone",
        "vodafone-idea": "vodafone",
    }
    if provider is not None:
        if isinstance(provider, Provider):
            prov = provider
        else:
            prov = Provider(prov_map.get(str(provider).lower(), str(provider).lower()))
    else:
        console.print("1) Tata  2) Jio  3) Airtel  4) Vodafone-Idea")
        choice = ask_choice(
            "Provider", ["1", "2", "3", "4", "tata", "jio", "airtel", "vodafone"], default="1"
        )
        prov = Provider(prov_map[choice.lower()])

    site_nm = site or ask_text("Site name", default=f"{prov.value}-site")
    plat = platform if isinstance(platform, Platform) else Platform(platform)

    console.print(Panel("Step 2/6 — Carrier sheet / inventory", title=""))
    hits: dict = {}
    warnings: list[str] = []
    confidence = 0.0
    if sheet_file is None and not yes:
        path_s = ask_text("Path to carrier sheet (.txt/.pdf text extract)", default="")
        sheet_file = Path(path_s) if path_s.strip() else None
    if sheet_file and sheet_file.exists():
        parsed = parse_carrier_sheet(
            sheet_file.read_text(errors="ignore"), hint_provider=prov
        )
        hits = dict(parsed.raw_hits)
        if parsed.media_ips:
            hits["media_ips"] = ",".join(parsed.media_ips)
        warnings = parsed.warnings
        confidence = parsed.confidence
        console.print(
            Panel(
                f"Parse confidence: {confidence:.0%}\n"
                f"Hits: {hits}\n"
                f"Warnings: {warnings or 'none'}",
                title="Carrier sheet parse",
            )
        )
    elif sheet_file:
        console.print(f"[yellow]Sheet not found: {sheet_file}[/yellow]")

    def _ask(label: str, key: str, default: str = "") -> str:
        d = str(hits.get(key) or default)
        if yes and d:
            return d
        return ask_text(label, default=d)

    customer_ip = _ask("Customer / LAN IP (Ameyo SIP NIC)", "customer_ip")
    gateway_ip = _ask("Carrier gateway IP", "gateway_ip")
    sbc_ip = _ask("Carrier SBC / peer IP", "sbc_ip")
    pilot = _ask("Pilot / DID", "pilot")
    password = _ask("SIP password (if any)", "password")
    media_raw = hits.get("media_ips") or ""
    if not yes:
        media_raw = ask_text("Media IPs (comma-separated, optional)", default=str(media_raw))
    media_ips = [x.strip() for x in str(media_raw).split(",") if x.strip()]

    console.print(Panel("Step 3/6 — Choose SIP interface", title=""))
    ssh = _prompt_ssh(None, yes=yes)
    if ssh is not None:
        ssh = _try_ssh(ssh)

    # Build draft inventory for NIC picker
    inv = Inventory(
        site=Site(name=site_nm),
        provider=prov,
        platform=plat,
        sip_driver=SipDriver.PJSIP if plat == Platform.FREEPBX else SipDriver.CHAN_SIP,
        network=NetworkConfig(
            interface=iface or "eth1",
            customer_ip=customer_ip,
            gateway_ip=gateway_ip,
            sbc_ip=sbc_ip,
            netmask="255.255.255.252",
            media_ips=media_ips,
            sip_transport="both",
        ),
        sip=SipConfig(pilot=pilot or "0000000000", password=password or None),
        ssh=ssh,
    )

    try:
        chosen = choose_interface(
            inv,
            ask=not yes,
            interface=iface,
            use_ssh=bool(ssh),
            non_interactive_default=yes,
        )
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]Interface discovery issue: {e}[/yellow]")
        chosen = iface or inv.network.interface or "eth1"
        console.print(f"Using interface: {chosen}")
        inv.network.interface = chosen

    dest = Path(out_root) / site_nm
    dest.mkdir(parents=True, exist_ok=True)
    inv_path = Path(inventory_out) if inventory_out else (dest / "inventory.yaml")
    write_inventory(inv, inv_path)
    console.print(f"Wrote inventory {inv_path}")

    console.print(Panel("Step 4/6 — Generate artifacts", title=""))
    arts = generate(inv, dest)
    console.print(f"Generated {len(arts)} files → {dest}")

    console.print(Panel("Step 5/6 — Verify + preflight", title=""))
    try:
        vreport = verify(inv, use_ssh=bool(ssh), artifacts_dir=dest)
        _print_report("Verify", vreport)
        (dest / "verify_report.json").write_text(
            vreport.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]Verify skipped due to error: {e}[/yellow]")

    try:
        pre = run_preflight(inv, use_ssh=bool(ssh))
        _print_report("Preflight", pre)
        (dest / "preflight_report.json").write_text(
            pre.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]Preflight skipped due to error: {e}[/yellow]")

    console.print(Panel("Step 6/6 — Apply (optional)", title=""))
    do_apply = False
    if not skip_apply and not yes:
        do_apply = ask_yes_no("Apply network configs now? (destructive)", default=False)
    if do_apply:
        from sipauto.workflow.apply import apply_network, apply_sip, reload_services

        try:
            for line in apply_network(inv, dry_run=False, allow_local=True):
                console.print(line)
            if ask_yes_no("Also push Ameyo/Asterisk snippets?", default=False):
                for line in apply_sip(
                    inv, dest, dry_run=False, ameyo_write=True, allow_local=True
                ):
                    console.print(line)
            if ask_yes_no("Reload Asterisk peers?", default=True):
                for line in reload_services(inv, dry_run=False, allow_local=True):
                    console.print(line)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Apply failed: {e}[/red]")
    else:
        console.print("Skipped apply. Review artifacts, then:")
        console.print(f"  python3 -m sipauto apply-net -i {inv_path}")
        console.print(f"  python3 -m sipauto apply-sip -i {inv_path} --ameyo-write")
        console.print(f"  python3 -m sipauto reload -i {inv_path}")

    console.print(
        Panel(f"Inventory: {inv_path}\nArtifacts: {dest}", title="Wizard complete")
    )
    return inv_path
