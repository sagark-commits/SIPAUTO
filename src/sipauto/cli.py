"""SIPAUTO CLI — stdlib argparse (no pip deps required).

Recommended:
  python3 -m sipauto wizard --sheet examples/carrier_sheets/tata_sample.txt
  # or after optional pip install: sipauto wizard ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from sipauto import __version__
from sipauto.models import Platform, Provider
from sipauto.network.interfaces import (
    choose_interface,
    discover_interfaces,
    print_interfaces,
    prompt_sip_interface,
    save_interface_to_inventory,
)
from sipauto.parser.carrier_sheet import parse_carrier_sheet
from sipauto.util.console import ask_yes_no, console, print_table
from sipauto.workflow.apply import apply_network, apply_sip, reload_services
from sipauto.workflow.generate import generate
from sipauto.workflow.inventory_io import load_inventory, save_inventory
from sipauto.workflow.preflight import run_preflight
from sipauto.workflow.registry import diagnose_text, watch_registry
from sipauto.workflow.rollback import plan_rollback, rollback
from sipauto.workflow.verify import verify
from sipauto.workflow.wizard import run_wizard


@dataclass
class InvokeResult:
    exit_code: int
    output: str


class _App:
    """Minimal stand-in so tests can call invoke(app, args)."""

    def __call__(self, argv: Optional[list[str]] = None) -> int:
        return main(argv)


app = _App()


def invoke(args: list[str]) -> InvokeResult:
    """Test helper (replaces typer.CliRunner)."""
    from io import StringIO
    from contextlib import redirect_stdout, redirect_stderr

    buf = StringIO()
    code = 0
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            try:
                code = main(args)
            except SystemExit as e:
                code = int(e.code) if e.code is not None else 0
    except Exception as exc:  # noqa: BLE001
        buf.write(str(exc))
        code = 1
    return InvokeResult(exit_code=code, output=buf.getvalue())


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
        non_interactive_default=not ask_iface,
    )
    if save_iface:
        save_interface_to_inventory(str(inventory), chosen)
        console.print(f"[green]Saved[/green] network.interface={chosen} → {inventory}")
    return chosen


def _add_inv(p: argparse.ArgumentParser, required: bool = True) -> None:
    p.add_argument(
        "-i",
        "--inventory",
        type=Path,
        required=required,
        help="Inventory YAML/JSON",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sipauto",
        description=(
            "Automate on-prem SIP trunk setup (Tata/Jio/Airtel/Vodafone) "
            "for Ameyo+Asterisk and FreePBX. Zero pip deps — stdlib + OpenSSH."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("version", help="Print version")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("ifaces", help="List network interfaces")
    p.add_argument("-i", "--inventory", type=Path)
    p.add_argument("--ssh", action="store_true")
    p.add_argument("--all", dest="all_ifaces", action="store_true")
    p.set_defaults(func=cmd_ifaces)

    p = sub.add_parser("validate", help="Validate inventory")
    _add_inv(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("generate", help="Generate network + SIP artifacts")
    _add_inv(p)
    p.add_argument("-o", "--out", type=Path)
    p.add_argument("--ask-iface", action="store_true", default=True)
    p.add_argument("--no-ask-iface", action="store_false", dest="ask_iface")
    p.add_argument("-I", "--interface")
    p.add_argument("--ssh", action="store_true")
    p.add_argument("--all-ifaces", action="store_true")
    p.add_argument("--save-iface", action="store_true")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("verify", help="Verify ports/reachability")
    _add_inv(p)
    p.add_argument("-o", "--out", type=Path)
    p.add_argument("--ssh", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("apply-net", help="Apply ifcfg/routes/hosts")
    _add_inv(p)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument("--ask-iface", action="store_true", default=True)
    p.add_argument("--no-ask-iface", action="store_false", dest="ask_iface")
    p.add_argument("-I", "--interface")
    p.add_argument("--all-ifaces", action="store_true")
    p.add_argument("--save-iface", action="store_true")
    p.add_argument("--local", action="store_true", help="Allow apply on this host without SSH")
    p.set_defaults(func=cmd_apply_net)

    p = sub.add_parser("apply-sip", help="Apply SIP artifacts")
    _add_inv(p)
    p.add_argument("-o", "--out", type=Path)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument(
        "--ameyo-write",
        dest="ameyo_write",
        action="store_const",
        const=True,
        default=None,
    )
    p.add_argument(
        "--no-ameyo-write",
        dest="ameyo_write",
        action="store_const",
        const=False,
    )
    p.add_argument("--local", action="store_true")
    p.set_defaults(func=cmd_apply_sip)

    p = sub.add_parser("reload", help="Reload Asterisk SIP/PJSIP/RTP")
    _add_inv(p)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--local", action="store_true")
    p.set_defaults(func=cmd_reload)

    p = sub.add_parser("run", help="generate → verify → optional apply")
    _add_inv(p)
    p.add_argument("-o", "--out", type=Path)
    p.add_argument("--ssh", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument("--ask-iface", action="store_true", default=True)
    p.add_argument("--no-ask-iface", action="store_false", dest="ask_iface")
    p.add_argument("-I", "--interface")
    p.add_argument("--all-ifaces", action="store_true")
    p.add_argument("--save-iface", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("wizard", help="Guided setup wizard")
    p.add_argument("-o", "--out", type=Path, default=Path("out"))
    p.add_argument("-s", "--sheet", type=Path)
    p.add_argument("--inventory-out", type=Path)
    p.add_argument("-p", "--provider")
    p.add_argument("--platform", default="ameyo_asterisk")
    p.add_argument("--site")
    p.add_argument("-I", "--interface")
    p.add_argument("--skip-apply", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=cmd_wizard)

    p = sub.add_parser("parse-sheet", help="Parse carrier sheet → inventory")
    p.add_argument("-s", "--sheet", type=Path)
    p.add_argument("-p", "--provider")
    p.add_argument("--site", default="parsed-site")
    p.add_argument(
        "-I",
        "--interface",
        default=None,
        help="SIP NIC (if omitted, lists available NICs and asks)",
    )
    p.add_argument(
        "--ask-iface",
        action="store_true",
        default=True,
        help="List NICs and ask which to use for SIP (default)",
    )
    p.add_argument("--no-ask-iface", action="store_false", dest="ask_iface")
    p.add_argument("--platform", default="ameyo_asterisk")
    p.add_argument("-o", "--out", type=Path, default=Path("out/parsed-inventory.yaml"))
    p.set_defaults(func=cmd_parse_sheet)

    p = sub.add_parser("preflight", help="Pre-flight GREEN/YELLOW/RED")
    _add_inv(p)
    p.add_argument("--ssh", action="store_true")
    p.add_argument("-o", "--out", type=Path)
    p.add_argument(
        "--ask-iface",
        action="store_true",
        default=True,
        help="If inventory NIC is missing, list NICs and ask which to use (default)",
    )
    p.add_argument("--no-ask-iface", action="store_false", dest="ask_iface")
    p.add_argument(
        "-I",
        "--interface",
        help="Force SIP NIC (saved into inventory) before running checks",
    )
    p.add_argument(
        "--save-iface",
        action="store_true",
        default=True,
        help="Write chosen interface back into inventory (default)",
    )
    p.add_argument("--no-save-iface", action="store_false", dest="save_iface")
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("registry-watch", help="Poll SIP registry")
    _add_inv(p)
    p.add_argument("--polls", type=int, default=5)
    p.add_argument("--interval", type=float, default=3.0)
    p.add_argument("--options", action="store_true", default=True)
    p.add_argument("--no-options", action="store_false", dest="options")
    p.add_argument("--dial")
    p.add_argument("-o", "--out", type=Path)
    p.set_defaults(func=cmd_registry_watch)

    p = sub.add_parser("diagnose", help="Map SIP error text to fixes")
    p.add_argument("text", nargs="?")
    p.add_argument("-f", "--file", type=Path)
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("rollback", help="Restore *.sipauto.bak files")
    _add_inv(p)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=cmd_rollback)

    return parser


def cmd_version(_args: argparse.Namespace) -> int:
    console.print(__version__)
    return 0


def cmd_ifaces(args: argparse.Namespace) -> int:
    ssh_cfg = None
    default = None
    if args.inventory:
        inv = load_inventory(args.inventory)
        default = inv.network.interface
        if args.ssh and inv.ssh:
            ssh_cfg = inv.ssh
        elif args.ssh and not inv.ssh:
            console.print("[red]inventory.ssh is required for --ssh[/red]")
            return 2
    nics = discover_interfaces(ssh=ssh_cfg, include_virtual=args.all_ifaces)
    if not nics:
        console.print("[yellow]No interfaces found[/yellow]")
        return 1
    print_interfaces(nics, default=default)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    provider = inv.provider.value
    console.print(
        f"[green]OK[/green] {inv.site.name} provider={provider} platform={inv.platform.value}"
    )
    console.print(f"  SIP interface (inventory): {inv.network.interface}")
    code = 0
    if provider == "airtel" and not inv.sip.password:
        console.print("[red]FAIL[/red] airtel requires sip.password")
        code = 2
    if provider in ("jio", "airtel", "vodafone") and not inv.network.media_ips:
        console.print("[yellow]WARN[/yellow] media_ips empty — audio may fail")
    return code


def cmd_generate(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    chosen = _resolve_iface(
        args.inventory,
        inv,
        ask_iface=args.ask_iface,
        interface=args.interface,
        use_ssh=args.ssh,
        all_ifaces=args.all_ifaces,
        save_iface=args.save_iface,
    )
    dest = args.out or Path("out") / inv.site.name
    arts = generate(inv, dest)
    console.print(f"[green]Generated {len(arts)} files in {dest}[/green] (SIP iface={chosen})")
    for a in arts:
        console.print(f"  - {a.path}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    dest = _out_dir(args.inventory, args.out)
    report = verify(inv, use_ssh=args.ssh, artifacts_dir=dest)
    print_table(
        f"Verify — {report.confidence}",
        ["Check", "OK", "Severity", "Detail"],
        [[c.name, "yes" if c.ok else "no", c.severity, c.detail] for c in report.checks],
    )
    if report.next_actions:
        console.print("Next actions")
        for n in report.next_actions:
            console.print(f"  • {n}")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "verify_report.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return 1 if report.confidence == "RED" else 0


def cmd_apply_net(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    chosen = _resolve_iface(
        args.inventory,
        inv,
        ask_iface=args.ask_iface and not args.yes,
        interface=args.interface,
        use_ssh=bool(inv.ssh),
        all_ifaces=args.all_ifaces,
        save_iface=args.save_iface,
    )
    if not args.yes and not args.dry_run:
        host = inv.ssh.host if inv.ssh else "local"
        if not ask_yes_no(f"Apply network config on {host} for iface {chosen}?", default=False):
            return 1
    for line in apply_network(inv, dry_run=args.dry_run, allow_local=args.local):
        console.print(line)
    return 0


def cmd_apply_sip(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    dest = _out_dir(args.inventory, args.out)
    if not dest.exists():
        console.print("[red]Artifacts missing. Run generate (then verify) first.[/red]")
        return 2
    do_ameyo = False
    if inv.platform.value in ("ameyo_asterisk", "asterisk"):
        if args.ameyo_write is None:
            console.print(
                "[yellow]Ameyo write is optional.[/yellow]\n"
                "It writes Asterisk include snippets only; it does not create Call Manager UI rows.\n"
                f"Paste pack is already in: {dest}/ameyo/"
            )
            do_ameyo = ask_yes_no("Proceed with Ameyo/Asterisk file write?", default=False)
        else:
            do_ameyo = bool(args.ameyo_write)
    else:
        do_ameyo = True
    if not args.yes and not args.dry_run:
        host = inv.ssh.host if inv.ssh else "local"
        if not ask_yes_no(f"Apply SIP files to {host}?", default=False):
            return 1
    for line in apply_sip(
        inv, dest, ameyo_write=do_ameyo, dry_run=args.dry_run, allow_local=args.local
    ):
        console.print(line)
    return 0


def cmd_reload(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    for line in reload_services(inv, dry_run=args.dry_run, allow_local=args.local):
        console.print(line)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    dest = args.out or Path("out") / inv.site.name
    console.rule("0/4 choose SIP interface")
    chosen = _resolve_iface(
        args.inventory,
        inv,
        ask_iface=args.ask_iface and not args.yes,
        interface=args.interface,
        use_ssh=args.ssh,
        all_ifaces=args.all_ifaces,
        save_iface=args.save_iface,
    )
    console.print(f"SIP interface: {chosen}")
    console.rule("1/4 generate")
    arts = generate(inv, dest)
    console.print(f"Generated {len(arts)} files → {dest}")
    console.rule("2/4 verify")
    report = verify(inv, use_ssh=args.ssh, artifacts_dir=dest)
    console.print(json.dumps(report.model_dump(), indent=2))
    (dest / "verify_report.json").write_text(report.model_dump_json(indent=2) + "\n")
    if report.confidence == "RED" and args.apply:
        console.print("[red]Confidence RED — refusing apply. Fix checks first.[/red]")
        return 1
    if not args.apply:
        console.print("Stopped after generate+verify. Re-run with --apply --ssh to push.")
        return 0
    if not args.ssh and not inv.ssh:
        console.print("[red]--apply needs inventory.ssh or run on call server with --local[/red]")
        return 2
    console.rule("3/4 apply-net")
    if not args.yes:
        if not ask_yes_no(
            f"Apply network now on iface {inv.network.interface}?", default=False
        ):
            return 1
    for line in apply_network(inv, dry_run=False, allow_local=True):
        console.print(line)
    console.rule("4/4 apply-sip + reload")
    ameyo_env = os.environ.get("SIPAUTO_AMEYO_WRITE", "").strip() in ("1", "true", "yes")
    do_ameyo = False
    if inv.platform.value in ("ameyo_asterisk", "asterisk"):
        if args.yes and ameyo_env:
            do_ameyo = True
        else:
            do_ameyo = ask_yes_no("Write Ameyo/Asterisk include snippets?", default=False)
    else:
        do_ameyo = True
    for line in apply_sip(inv, dest, ameyo_write=do_ameyo, dry_run=False, allow_local=True):
        console.print(line)
    for line in reload_services(inv, dry_run=False, allow_local=True):
        console.print(line)
    console.print("[green]Done[/green]")
    return 0


def cmd_wizard(args: argparse.Namespace) -> int:
    if args.yes and (not args.sheet or not args.provider):
        console.print("[red]--yes requires --sheet and --provider[/red]")
        return 2
    path = run_wizard(
        out_root=args.out,
        sheet_file=args.sheet,
        inventory_out=args.inventory_out,
        provider=args.provider,
        platform=args.platform,
        site=args.site,
        interface=args.interface,
        skip_apply=args.skip_apply or args.yes,
        yes=args.yes,
    )
    console.print(f"Inventory: {path}")
    return 0


def cmd_parse_sheet(args: argparse.Namespace) -> int:
    if args.sheet:
        text = args.sheet.read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            console.print("[red]Provide --sheet FILE or pipe text on stdin[/red]")
            return 2
        text = sys.stdin.read()
    hint = Provider(args.provider) if args.provider else None
    parsed = parse_carrier_sheet(text, hint_provider=hint)
    print_table(
        f"Parse confidence {parsed.confidence:.0%}",
        ["Field", "Value"],
        [[k, v] for k, v in parsed.raw_hits.items()]
        + [
            ["media_ips", ", ".join(parsed.media_ips) or "-"],
            ["provider", (parsed.provider.value if parsed.provider else "-")],
        ],
    )
    for w in parsed.warnings:
        console.print(f"[yellow]WARN[/yellow] {w}")
    if parsed.missing_required():
        console.print(f"[red]Missing:[/red] {', '.join(parsed.missing_required())}")
        return 2

    # List available NICs and let the operator choose which one is for SIP
    console.print("")
    iface = prompt_sip_interface(
        prefer=args.interface,
        interactive=bool(args.ask_iface),
        force_prompt=bool(args.ask_iface),
    )

    plat = Platform(args.platform)
    inv = parsed.to_inventory(
        site_name=args.site,
        interface=iface,
        platform=plat,
        provider=hint or parsed.provider,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    save_inventory(args.out, inv)
    console.print(f"[green]Wrote[/green] {args.out}  (SIP iface={iface})")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)

    # Resolve SIP NIC first: list available interfaces and let operator choose
    need_pick = bool(args.interface) or bool(args.ask_iface)
    if need_pick:
        console.print("Step: choose SIP interface for preflight")
        chosen = choose_interface(
            inv,
            ask=bool(args.ask_iface),
            interface=args.interface,
            use_ssh=bool(args.ssh),
            force_prompt=bool(args.ask_iface),
            non_interactive_default=not args.ask_iface and not args.interface,
        )
        if args.save_iface and chosen != load_inventory(args.inventory).network.interface:
            save_interface_to_inventory(str(args.inventory), chosen)
            console.print(f"[green]Saved[/green] network.interface={chosen} → {args.inventory}")
        elif args.save_iface:
            save_interface_to_inventory(str(args.inventory), chosen)
            console.print(f"[green]Saved[/green] network.interface={chosen} → {args.inventory}")
        inv.network.interface = chosen

    report = run_preflight(inv, use_ssh=args.ssh)
    print_table(
        f"Preflight — {report.confidence}",
        ["Check", "OK", "Severity", "Detail"],
        [[c.name, "yes" if c.ok else "no", c.severity, c.detail] for c in report.checks],
    )
    if report.next_actions:
        console.print("Next actions")
        for n in report.next_actions:
            console.print(f"  • {n}")
    dest = args.out or _out_dir(args.inventory, None)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "preflight_report.json").write_text(report.model_dump_json(indent=2) + "\n")
    if report.confidence == "RED":
        return 1
    if report.confidence == "YELLOW":
        return 3
    return 0


def cmd_registry_watch(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    result = watch_registry(
        inv,
        polls=args.polls,
        interval=args.interval,
        options_probe=args.options,
        dial_test=args.dial,
    )
    console.print(
        f"Registered={result.registered}  OPTIONS={result.options_ok}  "
        f"errors={result.errors_seen or '-'}"
    )
    for c in result.checks:
        mark = "OK" if c.ok else "FAIL"
        console.print(f"  [{mark}] {c.name}: {c.detail}")
    for pb in result.playbooks:
        console.print(f"Playbook: {pb}")
    dest = args.out or _out_dir(args.inventory, None)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "registry_watch.txt").write_text(result.raw, encoding="utf-8")
    if not result.registered and inv.provider.value not in ("jio", "vodafone"):
        return 1
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    blob = args.file.read_text(encoding="utf-8") if args.file else (args.text or "")
    if not blob.strip():
        console.print("Provide text or --file")
        return 2
    hits = diagnose_text(blob)
    if not hits:
        console.print("No known SIP error codes found in text")
        return 1
    for h in hits:
        console.print(f"• {h}")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    inv = load_inventory(args.inventory)
    plan = plan_rollback(inv)
    console.print("Rollback plan")
    for a in plan.actions:
        console.print(f"  {a}")
    if not plan.backups and not args.dry_run:
        console.print("[yellow]No backups found[/yellow]")
        return 1
    if args.dry_run:
        return 0
    if not args.yes and not ask_yes_no("Restore backups now?", default=False):
        return 1
    for line in rollback(inv, dry_run=False):
        console.print(line)
    console.print("[green]Rollback complete[/green]")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    try:
        return int(func(args))
    except KeyboardInterrupt:
        console.print("\nInterrupted")
        return 130
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {exc}")
        return 1


def entrypoint() -> None:
    """Console-script entry (setuptools)."""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
