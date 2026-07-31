"""SIPAUTO CLI.

Recommended flow:
  1) sipauto generate          # asks which NIC for SIP
  2) sipauto verify [--ssh]
  3) sipauto apply-net --ssh   # asks again unless already chosen / --interface
  4) sipauto apply-sip --ssh   # asks before Ameyo write
  5) sipauto reload --ssh
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from sipauto import __version__
from sipauto.network.interfaces import (
    choose_interface,
    discover_interfaces,
    print_interfaces,
    save_interface_to_inventory,
)
from sipauto.workflow.apply import apply_network, apply_sip, reload_services
from sipauto.workflow.generate import generate
from sipauto.workflow.inventory_io import load_inventory
from sipauto.workflow.verify import verify

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


if __name__ == "__main__":
    app()
