"""Guided interactive wizard: provider → sheet → NIC → generate → verify/preflight → apply."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from sipauto.models import Inventory, Platform, Provider, SSHConfig
from sipauto.network.interfaces import choose_interface
from sipauto.parser.carrier_sheet import parse_carrier_sheet
from sipauto.workflow.apply import apply_network, apply_sip, reload_services
from sipauto.workflow.generate import generate
from sipauto.workflow.preflight import run_preflight
from sipauto.workflow.registry import watch_registry
from sipauto.workflow.verify import verify

console = Console()


def _pick_provider() -> Provider:
    console.print(Panel("Step 1/6 — Choose carrier provider", style="cyan"))
    mapping = {
        "1": Provider.TATA,
        "2": Provider.JIO,
        "3": Provider.AIRTEL,
        "4": Provider.VODAFONE,
        "tata": Provider.TATA,
        "jio": Provider.JIO,
        "airtel": Provider.AIRTEL,
        "vodafone": Provider.VODAFONE,
        "vi": Provider.VODAFONE,
    }
    console.print("1) Tata  2) Jio  3) Airtel  4) Vodafone-Idea")
    while True:
        raw = Prompt.ask("Provider", default="1").strip().lower()
        if raw in mapping:
            return mapping[raw]
        console.print("[red]Pick 1-4 or name[/red]")


def _pick_platform() -> Platform:
    console.print("Platform: 1) Ameyo+Asterisk  2) FreePBX  3) Asterisk")
    raw = Prompt.ask("Platform", default="1").strip()
    return {
        "1": Platform.AMEYO_ASTERISK,
        "2": Platform.FREEPBX,
        "3": Platform.ASTERISK,
        "ameyo": Platform.AMEYO_ASTERISK,
        "freepbx": Platform.FREEPBX,
        "asterisk": Platform.ASTERISK,
    }.get(raw.lower(), Platform.AMEYO_ASTERISK)


def _read_carrier_sheet() -> str:
    console.print(Panel("Step 2/6 — Paste carrier sheet / email text", style="cyan"))
    console.print(
        "[dim]Paste provisioning text, then finish with a line containing only "
        "END (or Ctrl+D).[/dim]"
    )
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


def _prompt_missing(parsed, provider: Provider) -> None:
    """Fill missing required fields interactively."""
    if not parsed.customer_ip:
        parsed.customer_ip = Prompt.ask("Customer IP")
    if not parsed.gateway_ip:
        parsed.gateway_ip = Prompt.ask("Gateway IP")
    if not parsed.sbc_ip:
        parsed.sbc_ip = Prompt.ask("SBC / SIP Server IP")
    if not parsed.pilot:
        parsed.pilot = Prompt.ask("Pilot / Hunt number")
    if provider == Provider.AIRTEL and not parsed.password:
        parsed.password = Prompt.ask("Airtel password", password=True)
    if provider in (Provider.JIO, Provider.AIRTEL, Provider.VODAFONE) and not parsed.media_ips:
        media = Prompt.ask("Media IP(s), comma-separated (optional)", default="")
        if media.strip():
            parsed.media_ips = [x.strip() for x in media.split(",") if x.strip()]
    if provider == Provider.TATA and not parsed.password:
        parsed.password = Prompt.ask("SIP password", default="1234")


def _maybe_ssh() -> Optional[SSHConfig]:
    console.print(Panel("SSH to call server (optional for local generate-only)", style="cyan"))
    if not Confirm.ask("Configure SSH for preflight/apply/registry?", default=False):
        return None
    host = Prompt.ask("SSH host")
    user = Prompt.ask("SSH user", default="root")
    port = int(Prompt.ask("SSH port", default="22"))
    key = Prompt.ask("SSH key path (blank for agent/password)", default="")
    password = None
    if not key:
        if Confirm.ask("Use password auth?", default=False):
            password = Prompt.ask("SSH password", password=True)
    return SSHConfig(
        host=host,
        user=user,
        port=port,
        key_path=key or None,
        password=password,
    )


def _print_report(title: str, report) -> None:
    table = Table(title=f"{title} — {report.confidence}")
    table.add_column("Check")
    table.add_column("OK")
    table.add_column("Sev")
    table.add_column("Detail")
    for c in report.checks:
        table.add_row(c.name, "yes" if c.ok else "no", c.severity, c.detail[:80])
    console.print(table)
    if report.next_actions:
        console.print("[bold]Next actions[/bold]")
        for a in report.next_actions:
            console.print(f"  • {a}")


def run_wizard(
    *,
    out_root: Path = Path("out"),
    sheet_file: Optional[Path] = None,
    inventory_out: Optional[Path] = None,
    provider: Optional[Provider] = None,
    platform: Optional[Platform] = None,
    site_name: Optional[str] = None,
    interface: Optional[str] = None,
    skip_apply: bool = False,
    non_interactive: bool = False,
) -> Path:
    """Run full interactive wizard. Returns path to written inventory YAML."""
    if provider is None:
        provider = _pick_provider() if not non_interactive else Provider.TATA
    if platform is None:
        platform = _pick_platform() if not non_interactive else Platform.AMEYO_ASTERISK
    site = site_name or (
        Prompt.ask("Site name", default=f"{provider.value}-site")
        if not non_interactive
        else f"{provider.value}-site"
    )

    text = sheet_file.read_text(encoding="utf-8") if sheet_file else (
        "" if non_interactive else _read_carrier_sheet()
    )
    if not text.strip():
        console.print("[yellow]Empty sheet — you'll enter fields manually.[/yellow]")
    parsed = parse_carrier_sheet(text, hint_provider=provider)
    if parsed.provider and parsed.provider != provider:
        console.print(
            f"[yellow]Sheet looks like {parsed.provider.value}; "
            f"you picked {provider.value}. Keeping your pick.[/yellow]"
        )
    parsed.provider = provider

    console.print(
        Panel(
            f"Parse confidence: {parsed.confidence:.0%}\n"
            f"Hits: {parsed.raw_hits}\n"
            f"Warnings: {parsed.warnings or 'none'}",
            title="Carrier sheet parse",
        )
    )
    if not non_interactive:
        _prompt_missing(parsed, provider)
    elif parsed.missing_required():
        raise SystemExit(
            f"Non-interactive wizard missing fields: {parsed.missing_required()}"
        )

    inv = parsed.to_inventory(site_name=site, platform=platform, provider=provider)

    console.print(Panel("Step 3/6 — Choose SIP interface", style="cyan"))
    ssh = None if non_interactive else _maybe_ssh()
    inv.ssh = ssh
    choose_interface(
        inv,
        ask=not non_interactive and interface is None,
        interface=interface,
        use_ssh=bool(ssh),
    )

    # Save inventory
    inv_path = inventory_out or (out_root / site / "inventory.yaml")
    inv_path.parent.mkdir(parents=True, exist_ok=True)
    # dump via model_dump for clean YAML
    data = inv.model_dump(mode="json")
    # strip nulls lightly
    inv_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    console.print(f"[green]Wrote inventory[/green] {inv_path}")

    console.print(Panel("Step 4/6 — Generate artifacts", style="cyan"))
    dest = out_root / site
    arts = generate(inv, dest)
    console.print(f"Generated {len(arts)} files → {dest}")

    console.print(Panel("Step 5/6 — Verify + preflight", style="cyan"))
    vreport = verify(inv, use_ssh=bool(ssh), artifacts_dir=dest)
    _print_report("Verify", vreport)
    (dest / "verify_report.json").write_text(vreport.model_dump_json(indent=2) + "\n")

    pre = run_preflight(inv, use_ssh=bool(ssh))
    _print_report("Preflight", pre)
    (dest / "preflight_report.json").write_text(pre.model_dump_json(indent=2) + "\n")

    if pre.confidence == "RED":
        console.print("[red]Preflight RED — fix issues before apply.[/red]")
        if not Confirm.ask("Continue to apply anyway?", default=False):
            console.print(f"Stopped. Inventory: {inv_path}")
            return inv_path

    console.print(Panel("Step 6/6 — Apply (optional)", style="cyan"))
    if skip_apply or non_interactive or not ssh:
        if not ssh:
            console.print("[yellow]No SSH configured — generate/verify only.[/yellow]")
        elif skip_apply or non_interactive:
            console.print("[cyan]Skipping apply (non-interactive / --skip-apply).[/cyan]")
        console.print(
            Panel(
                f"Done (no apply).\nInventory: {inv_path}\nArtifacts: {dest}",
                title="Wizard complete",
                style="green",
            )
        )
        return inv_path

    if Confirm.ask("Apply network (ifcfg/routes/hosts) now?", default=False):
        for line in apply_network(inv, dry_run=False):
            console.print(line)

    do_ameyo = False
    if inv.platform.value in ("ameyo_asterisk", "asterisk"):
        do_ameyo = Confirm.ask(
            "Write Ameyo/Asterisk include snippets? (optional)", default=False
        )
    else:
        do_ameyo = Confirm.ask("Write FreePBX/Asterisk SIP files?", default=True)

    if do_ameyo or inv.platform == Platform.FREEPBX:
        if Confirm.ask("Apply SIP files now?", default=False):
            for line in apply_sip(inv, dest, ameyo_write=do_ameyo, dry_run=False):
                console.print(line)
            if Confirm.ask("Reload Asterisk now?", default=True):
                for line in reload_services(inv, dry_run=False):
                    console.print(line)
            if Confirm.ask("Watch SIP registry / OPTIONS probe?", default=True):
                dial = Prompt.ask(
                    "Optional dial-test number (blank to skip)", default=""
                ).strip() or None
                watch = watch_registry(
                    inv, polls=5, interval=2.0, options_probe=True, dial_test=dial
                )
                console.print(
                    f"Registered={watch.registered} options_ok={watch.options_ok}"
                )
                for pb in watch.playbooks:
                    console.print(f"[yellow]Playbook:[/yellow] {pb}")
                (dest / "registry_watch.txt").write_text(watch.raw, encoding="utf-8")

    console.print(
        Panel(
            f"Done.\nInventory: {inv_path}\nArtifacts: {dest}\n"
            f"Rollback later: sipauto rollback -i {inv_path}",
            title="Wizard complete",
            style="green",
        )
    )
    return inv_path
