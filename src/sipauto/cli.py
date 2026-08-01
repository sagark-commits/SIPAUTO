"""SIPAUTO CLI.

Recommended flow:
  sipauto wizard                 # guided: provider → sheet → NIC → generate → preflight → apply
  or step-by-step:
  1) sipauto parse-sheet
  2) sipauto generate            # asks which NIC for SIP
  3) sipauto preflight [--ssh]
  4) sipauto apply-net / apply-sip
  5) sipauto registry-watch
  6) sipauto rollback            # if needed
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table

from sipauto import __version__
from sipauto.models import Platform, Provider
from sipauto.network.interfaces import (
    choose_interface,
    discover_interfaces,
    print_interfaces,
    save_interface_to_inventory,
)
from sipauto.parser.carrier_sheet import parse_carrier_sheet
from sipauto.workflow.apply import apply_network, apply_sip, reload_services
from sipauto.workflow.generate import generate
from sipauto.workflow.inventory_io import load_inventory
from sipauto.workflow.preflight import run_preflight
from sipauto.workflow.registry import diagnose_text, watch_registry
from sipauto.workflow.rollback import plan_rollback, rollback
from sipauto.workflow.verify import verify
from sipauto.workflow.wizard import run_wizard

app = typer.Typer(
    name="sipauto",
    help="Automate on-prem SIP trunk setup (Tata/Jio/Airtel/Vodafone) for Ameyo+Asterisk and FreePBX.",
    no_args_is_help=True,
)
console = Console()


def _out_dir(inv_path: Path, explicit: Optional[Path]) -> Path:
    if explicit:
        return explicit
    inv = load_inventory(inv_path)
    return Path("out") / inv.site.name


def _resolve_iface(
    inventory: Path,
    inv,
    *,
    ask_iface: bool,
    interface: Optional[str],
    use_ssh: bool,
    all_ifaces: bool,
    save_iface: bool,
) -> str:
    chosen = choose_interface(
        inv,
        ask=ask_iface,
        interface=interface,
        use_ssh=use_ssh,
        include_virtual=all_ifaces,
    )
    if save_iface and chosen != load_inventory(inventory).network.interface:
        save_interface_to_inventory(str(inventory), chosen)
        console.print(f"[green]Saved[/green] network.interface={chosen} → {inventory}")
    elif save_iface:
        # still save if file had different formatting / ensure written
        save_interface_to_inventory(str(inventory), chosen)
        console.print(f"[green]Saved[/green] network.interface={chosen} → {inventory}")
    return chosen


@app.callback()
def main() -> None:
    """SIPAUTO — SIP configuration automation."""


@app.command("version")
def version_cmd() -> None:
    """Print version."""
    console.print(__version__)


@app.command("ifaces")
def ifaces_cmd(
    inventory: Optional[Path] = typer.Option(
        None, "--inventory", "-i", exists=True, readable=True, help="Optional; uses ssh: if set"
    ),
    ssh: bool = typer.Option(False, "--ssh", help="List interfaces on remote call server"),
    all_ifaces: bool = typer.Option(False, "--all", help="Include virtual interfaces"),
) -> None:
    """List network interfaces (local or via SSH) with link/speed when available."""
    ssh_cfg = None
    default = None
    if inventory:
        inv = load_inventory(inventory)
        default = inv.network.interface
        if ssh and inv.ssh:
            ssh_cfg = inv.ssh
        elif ssh and not inv.ssh:
            console.print("[red]inventory.ssh is required for --ssh[/red]")
            raise typer.Exit(2)
    nics = discover_interfaces(ssh=ssh_cfg, include_virtual=all_ifaces)
    if not nics:
        console.print("[yellow]No interfaces found[/yellow]")
        raise typer.Exit(1)
    print_interfaces(nics, default=default)


@app.command("validate")
def validate_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
) -> None:
    """Validate inventory YAML against schema + provider rules."""
    inv = load_inventory(inventory)
    provider = inv.provider.value
    console.print(f"[green]OK[/green] {inv.site.name} provider={provider} platform={inv.platform.value}")
    console.print(f"  SIP interface (inventory): {inv.network.interface}")
    if provider == "airtel" and not inv.sip.password:
        console.print("[red]FAIL[/red] airtel requires sip.password")
        raise typer.Exit(2)
    if provider in ("jio", "airtel", "vodafone") and not inv.network.media_ips:
        console.print("[yellow]WARN[/yellow] media_ips empty — audio may fail")


@app.command("generate")
def generate_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output directory"),
    ask_iface: bool = typer.Option(
        True,
        "--ask-iface/--no-ask-iface",
        help="Ask which NIC to use for SIP (default: ask)",
    ),
    interface: Optional[str] = typer.Option(
        None, "--interface", "-I", help="SIP NIC name (skips prompt)"
    ),
    ssh: bool = typer.Option(
        False, "--ssh", help="Discover interfaces on remote host (inventory.ssh)"
    ),
    all_ifaces: bool = typer.Option(False, "--all-ifaces", help="Include virtual NICs in picker"),
    save_iface: bool = typer.Option(
        False, "--save-iface", help="Write chosen interface back into inventory YAML"
    ),
) -> None:
    """Generate network + SIP artifacts (asks which interface for SIP by default)."""
    inv = load_inventory(inventory)
    chosen = _resolve_iface(
        inventory,
        inv,
        ask_iface=ask_iface,
        interface=interface,
        use_ssh=ssh,
        all_ifaces=all_ifaces,
        save_iface=save_iface,
    )
    dest = out or Path("out") / inv.site.name
    arts = generate(inv, dest)
    console.print(
        f"[green]Generated {len(arts)} files in {dest}[/green] "
        f"(SIP iface={chosen})"
    )
    for a in arts:
        console.print(f"  - {a.path}")


@app.command("verify")
def verify_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
    ssh: bool = typer.Option(False, "--ssh", help="Run checks on call server via SSH"),
) -> None:
    """Verify ports/reachability/registry. Run after generate."""
    inv = load_inventory(inventory)
    dest = _out_dir(inventory, out)
    report = verify(inv, use_ssh=ssh, artifacts_dir=dest)
    table = Table(title=f"Verify — {report.confidence}")
    table.add_column("Check")
    table.add_column("OK")
    table.add_column("Severity")
    table.add_column("Detail")
    for c in report.checks:
        table.add_row(c.name, "yes" if c.ok else "no", c.severity, c.detail)
    console.print(table)
    if report.next_actions:
        console.print("[bold]Next actions[/bold]")
        for n in report.next_actions:
            console.print(f"  • {n}")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "verify_report.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    if report.confidence == "RED":
        raise typer.Exit(1)


@app.command("apply-net")
def apply_net_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ask_iface: bool = typer.Option(
        True,
        "--ask-iface/--no-ask-iface",
        help="Ask which NIC to configure for SIP (default: ask)",
    ),
    interface: Optional[str] = typer.Option(
        None, "--interface", "-I", help="SIP NIC name (skips prompt)"
    ),
    all_ifaces: bool = typer.Option(False, "--all-ifaces"),
    save_iface: bool = typer.Option(False, "--save-iface"),
) -> None:
    """SSH-apply Rocky/RHEL ifcfg + routes + hosts, then reapply NIC."""
    inv = load_inventory(inventory)
    chosen = _resolve_iface(
        inventory,
        inv,
        ask_iface=ask_iface and not yes,
        interface=interface,
        use_ssh=True,
        all_ifaces=all_ifaces,
        save_iface=save_iface,
    )
    if not yes and not dry_run:
        typer.confirm(
            f"Apply network config on {inv.ssh.host if inv.ssh else '?'} "
            f"for iface {chosen}?",
            abort=True,
        )
    logs = apply_network(inv, dry_run=dry_run)
    for line in logs:
        console.print(line)


@app.command("apply-sip")
def apply_sip_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    ameyo_write: Optional[bool] = typer.Option(
        None,
        "--ameyo-write/--no-ameyo-write",
        help="Write Ameyo/Asterisk include snippets (asked interactively if omitted)",
    ),
) -> None:
    """SSH-apply SIP artifacts. For Ameyo, asks before write (generate → verify first)."""
    inv = load_inventory(inventory)
    dest = _out_dir(inventory, out)
    if not dest.exists():
        console.print("[red]Artifacts missing. Run generate (then verify) first.[/red]")
        raise typer.Exit(2)

    do_ameyo = False
    if inv.platform.value in ("ameyo_asterisk", "asterisk"):
        if ameyo_write is None:
            console.print(
                "[yellow]Ameyo write is optional.[/yellow]\n"
                "It writes Asterisk include snippets only; it does not create Call Manager UI rows.\n"
                f"Paste pack is already in: {dest}/ameyo/"
            )
            do_ameyo = typer.confirm("Proceed with Ameyo/Asterisk file write?", default=False)
        else:
            do_ameyo = ameyo_write
    else:
        do_ameyo = True

    if not yes and not dry_run:
        typer.confirm(f"Apply SIP files via SSH to {inv.ssh.host if inv.ssh else '?'}?", abort=True)

    logs = apply_sip(inv, dest, ameyo_write=do_ameyo, dry_run=dry_run)
    for line in logs:
        console.print(line)


@app.command("reload")
def reload_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Reload Asterisk SIP/PJSIP/RTP via SSH."""
    inv = load_inventory(inventory)
    logs = reload_services(inv, dry_run=dry_run)
    for line in logs:
        console.print(line)


@app.command("run")
def run_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
    ssh: bool = typer.Option(False, "--ssh", help="Enable SSH verify/apply/reload"),
    apply: bool = typer.Option(False, "--apply", help="Apply network+SIP after verify"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    ask_iface: bool = typer.Option(
        True,
        "--ask-iface/--no-ask-iface",
        help="Ask which NIC to use for SIP before generate (default: ask)",
    ),
    interface: Optional[str] = typer.Option(
        None, "--interface", "-I", help="SIP NIC name (skips prompt)"
    ),
    all_ifaces: bool = typer.Option(False, "--all-ifaces"),
    save_iface: bool = typer.Option(False, "--save-iface"),
) -> None:
    """Full flow: pick SIP NIC → generate → verify → (optional) apply-net/apply-sip/reload.

    Ameyo write is always confirmed interactively unless --yes and
    SIPAUTO_AMEYO_WRITE=1 is set.
    """
    import os

    inv = load_inventory(inventory)
    dest = out or Path("out") / inv.site.name

    console.rule("0/4 choose SIP interface")
    chosen = _resolve_iface(
        inventory,
        inv,
        ask_iface=ask_iface and not yes,
        interface=interface,
        use_ssh=ssh,
        all_ifaces=all_ifaces,
        save_iface=save_iface,
    )
    console.print(f"SIP interface: {chosen}")

    console.rule("1/4 generate")
    arts = generate(inv, dest)
    console.print(f"Generated {len(arts)} files → {dest}")

    console.rule("2/4 verify")
    report = verify(inv, use_ssh=ssh, artifacts_dir=dest)
    console.print(json.dumps(report.model_dump(), indent=2))
    (dest / "verify_report.json").write_text(report.model_dump_json(indent=2) + "\n")
    if report.confidence == "RED" and apply:
        console.print("[red]Confidence RED — refusing apply. Fix checks first.[/red]")
        raise typer.Exit(1)

    if not apply:
        console.print("[cyan]Stopped after generate+verify. Re-run with --apply --ssh to push.[/cyan]")
        return

    if not ssh:
        console.print("[red]--apply requires --ssh[/red]")
        raise typer.Exit(2)

    console.rule("3/4 apply-net")
    if not yes:
        typer.confirm(f"Apply network now on iface {inv.network.interface}?", abort=True)
    for line in apply_network(inv, dry_run=False):
        console.print(line)

    console.rule("4/4 apply-sip + reload")
    ameyo_env = os.environ.get("SIPAUTO_AMEYO_WRITE", "").strip() in ("1", "true", "yes")
    do_ameyo = False
    if inv.platform.value in ("ameyo_asterisk", "asterisk"):
        if yes and ameyo_env:
            do_ameyo = True
        else:
            do_ameyo = typer.confirm("Write Ameyo/Asterisk include snippets?", default=False)
    else:
        do_ameyo = True

    for line in apply_sip(inv, dest, ameyo_write=do_ameyo, dry_run=False):
        console.print(line)
    for line in reload_services(inv, dry_run=False):
        console.print(line)
    console.print("[green]Done[/green]")


@app.command("wizard")
def wizard_cmd(
    out: Path = typer.Option(Path("out"), "--out", "-o"),
    sheet: Optional[Path] = typer.Option(
        None, "--sheet", "-s", exists=True, readable=True, help="Carrier sheet text file"
    ),
    inventory_out: Optional[Path] = typer.Option(
        None, "--inventory-out", help="Where to write generated inventory YAML"
    ),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),
    platform: str = typer.Option("ameyo_asterisk", "--platform"),
    site: Optional[str] = typer.Option(None, "--site"),
    interface: Optional[str] = typer.Option(None, "--interface", "-I"),
    skip_apply: bool = typer.Option(False, "--skip-apply"),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Non-interactive (requires --sheet and --provider)"
    ),
) -> None:
    """Guided flow: provider → paste sheet → NIC → generate → preflight → optional apply."""
    if yes and (not sheet or not provider):
        console.print("[red]--yes requires --sheet and --provider[/red]")
        raise typer.Exit(2)
    path = run_wizard(
        out_root=out,
        sheet_file=sheet,
        inventory_out=inventory_out,
        provider=Provider(provider) if provider else None,
        platform=Platform(platform),
        site_name=site,
        interface=interface,
        skip_apply=skip_apply or yes,
        non_interactive=yes,
    )
    console.print(f"Inventory: {path}")


@app.command("parse-sheet")
def parse_sheet_cmd(
    sheet: Optional[Path] = typer.Option(
        None, "--sheet", "-s", exists=True, readable=True, help="Text file (else stdin)"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="tata|jio|airtel|vodafone"
    ),
    site: str = typer.Option("parsed-site", "--site"),
    interface: str = typer.Option("eth1", "--interface", "-I"),
    platform: str = typer.Option("ameyo_asterisk", "--platform"),
    out: Path = typer.Option(Path("out/parsed-inventory.yaml"), "--out", "-o"),
) -> None:
    """Parse carrier delivery sheet/email text into inventory YAML."""
    if sheet:
        text = sheet.read_text(encoding="utf-8")
    else:
        import sys

        if sys.stdin.isatty():
            console.print("[red]Provide --sheet FILE or pipe text on stdin[/red]")
            raise typer.Exit(2)
        text = sys.stdin.read()
    hint = Provider(provider) if provider else None
    parsed = parse_carrier_sheet(text, hint_provider=hint)
    table = Table(title=f"Parse confidence {parsed.confidence:.0%}")
    table.add_column("Field")
    table.add_column("Value")
    for k, v in parsed.raw_hits.items():
        table.add_row(k, v)
    table.add_row("media_ips", ", ".join(parsed.media_ips) or "-")
    table.add_row("provider", (parsed.provider.value if parsed.provider else "-"))
    console.print(table)
    for w in parsed.warnings:
        console.print(f"[yellow]WARN[/yellow] {w}")
    if parsed.missing_required():
        console.print(f"[red]Missing:[/red] {', '.join(parsed.missing_required())}")
        raise typer.Exit(2)
    plat = Platform(platform)
    inv = parsed.to_inventory(
        site_name=site,
        interface=interface,
        platform=plat,
        provider=hint or parsed.provider,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(inv.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out}")


@app.command("preflight")
def preflight_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    ssh: bool = typer.Option(False, "--ssh"),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
) -> None:
    """Pre-flight checklist with GREEN/YELLOW/RED before apply."""
    inv = load_inventory(inventory)
    report = run_preflight(inv, use_ssh=ssh)
    table = Table(title=f"Preflight — {report.confidence}")
    table.add_column("Check")
    table.add_column("OK")
    table.add_column("Severity")
    table.add_column("Detail")
    for c in report.checks:
        table.add_row(c.name, "yes" if c.ok else "no", c.severity, c.detail)
    console.print(table)
    if report.next_actions:
        console.print("[bold]Next actions[/bold]")
        for n in report.next_actions:
            console.print(f"  • {n}")
    dest = out or _out_dir(inventory, None)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "preflight_report.json").write_text(report.model_dump_json(indent=2) + "\n")
    if report.confidence == "RED":
        raise typer.Exit(1)
    if report.confidence == "YELLOW":
        raise typer.Exit(3)


@app.command("registry-watch")
def registry_watch_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    polls: int = typer.Option(5, "--polls"),
    interval: float = typer.Option(3.0, "--interval"),
    options: bool = typer.Option(True, "--options/--no-options"),
    dial: Optional[str] = typer.Option(None, "--dial", help="Optional originate test number"),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
) -> None:
    """Poll sip/pjsip registry, OPTIONS probe, map 407/403/480 to fixes."""
    inv = load_inventory(inventory)
    result = watch_registry(
        inv, polls=polls, interval=interval, options_probe=options, dial_test=dial
    )
    console.print(
        f"Registered=[bold]{result.registered}[/bold]  OPTIONS={result.options_ok}  "
        f"errors={result.errors_seen or '-'}"
    )
    for c in result.checks:
        mark = "OK" if c.ok else "FAIL"
        console.print(f"  [{mark}] {c.name}: {c.detail}")
    for pb in result.playbooks:
        console.print(f"[yellow]Playbook:[/yellow] {pb}")
    dest = out or _out_dir(inventory, None)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "registry_watch.txt").write_text(result.raw, encoding="utf-8")
    if not result.registered and inv.provider.value not in ("jio", "vodafone"):
        raise typer.Exit(1)


@app.command("diagnose")
def diagnose_cmd(
    text: Optional[str] = typer.Argument(None, help="Error snippet"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", exists=True),
) -> None:
    """Map SIP error text (407/403/480/…) to documented fixes."""
    blob = file.read_text(encoding="utf-8") if file else (text or "")
    if not blob.strip():
        console.print("Provide text or --file")
        raise typer.Exit(2)
    hits = diagnose_text(blob)
    if not hits:
        console.print("No known SIP error codes found in text")
        raise typer.Exit(1)
    for h in hits:
        console.print(f"• {h}")


@app.command("rollback")
def rollback_cmd(
    inventory: Path = typer.Option(..., "--inventory", "-i", exists=True, readable=True),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Restore *.sipauto.bak (ifcfg/routes/hosts/asterisk includes) and reload."""
    inv = load_inventory(inventory)
    plan = plan_rollback(inv)
    console.print("[bold]Rollback plan[/bold]")
    for a in plan.actions:
        console.print(f"  {a}")
    if not plan.backups and not dry_run:
        console.print("[yellow]No backups found[/yellow]")
        raise typer.Exit(1)
    if dry_run:
        return
    if not yes:
        typer.confirm("Restore backups now?", abort=True)
    for line in rollback(inv, dry_run=False):
        console.print(line)
    console.print("[green]Rollback complete[/green]")


if __name__ == "__main__":
    app()
