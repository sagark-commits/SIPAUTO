"""SSH helper using system OpenSSH (no paramiko / no pip crypto deps)."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sipauto.models import SSHConfig
from sipauto.util.netcheck import validate_host_or_raise


@dataclass
class SSHResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class SSHError(RuntimeError):
    pass


class SSHClient:
    """Thin wrapper around `ssh` / `scp`. Prefers key/agent; optional sshpass."""

    def __init__(self, cfg: SSHConfig):
        self.cfg = cfg
        validate_host_or_raise(cfg.host, "SSH host")
        self._tmpdir: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> "SSHClient":
        # probe connectivity
        probe = self.run("true", timeout=self.cfg.connect_timeout)
        if not probe.ok and "Permission denied" in (probe.stderr + probe.stdout):
            raise SSHError(
                "SSH authentication failed. Provide a key path (~/.ssh/id_rsa) "
                "or enable password auth with sshpass installed, or run sipauto "
                "locally on the call server (skip SSH)."
            )
        if not probe.ok:
            raise SSHError(
                f"SSH to {self.cfg.user}@{self.cfg.host}:{self.cfg.port} failed: "
                f"{(probe.stderr or probe.stdout).strip()[:300]}"
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmpdir:
            self._tmpdir.cleanup()
            self._tmpdir = None

    def _base_ssh(self) -> list[str]:
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes" if not self.cfg.password else "BatchMode=no",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={self.cfg.connect_timeout}",
            "-p",
            str(self.cfg.port),
        ]
        if self.cfg.key_path:
            cmd.extend(["-i", str(Path(self.cfg.key_path).expanduser())])
        cmd.append(f"{self.cfg.user}@{self.cfg.host}")
        return cmd

    def _wrap_password(self, cmd: list[str]) -> list[str]:
        if not self.cfg.password:
            return cmd
        if not _have("sshpass"):
            raise SSHError(
                "Password auth requested but `sshpass` is not installed. "
                "Install sshpass, or use an SSH key, or run locally without SSH."
            )
        return ["sshpass", "-p", self.cfg.password, *cmd]

    def run(self, command: str, timeout: int = 120, check: bool = False) -> SSHResult:
        """Run remote command. `check` is accepted for API compat (never raises)."""
        _ = check
        cmd = self._wrap_password(self._base_ssh() + [command])
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise SSHError(
                "`ssh` client not found. Install openssh-clients "
                "(dnf install -y openssh-clients) or run sipauto locally on the server."
            ) from exc
        except subprocess.TimeoutExpired:
            return SSHResult(exit_code=124, stdout="", stderr="SSH command timed out")
        return SSHResult(proc.returncode, proc.stdout or "", proc.stderr or "")

    def write_file(self, remote_path: str, content: str, mode: int = 0o644) -> None:
        # backup if exists
        self.run(
            f"if [ -f {shlex.quote(remote_path)} ]; then "
            f"cp -a {shlex.quote(remote_path)} {shlex.quote(remote_path + '.sipauto.bak')}; fi"
        )
        if self._tmpdir is None:
            self._tmpdir = tempfile.TemporaryDirectory(prefix="sipauto-ssh-")
        local = Path(self._tmpdir.name) / Path(remote_path).name
        local.write_text(content, encoding="utf-8")
        scp = [
            "scp",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={self.cfg.connect_timeout}",
            "-P",
            str(self.cfg.port),
        ]
        if self.cfg.key_path:
            scp.extend(["-i", str(Path(self.cfg.key_path).expanduser())])
        scp.extend([str(local), f"{self.cfg.user}@{self.cfg.host}:{remote_path}"])
        scp = self._wrap_password(scp)
        proc = subprocess.run(scp, check=False, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise SSHError(f"scp failed: {(proc.stderr or proc.stdout)[:300]}")
        self.run(f"chmod {mode:o} {shlex.quote(remote_path)}")

    def append_unique_hosts(self, entries: list[str]) -> SSHResult:
        script_parts = [
            "set -e",
            "if [ -f /etc/hosts ] && [ ! -f /etc/hosts.sipauto.bak ]; then "
            "cp -a /etc/hosts /etc/hosts.sipauto.bak; fi",
        ]
        for line in entries:
            _ip, _, name = line.partition(" ")
            name = name.strip().replace("'", "")
            script_parts.append(
                "grep -qE '(^|[[:space:]])"
                + name
                + "([[:space:]]|$)' /etc/hosts || echo "
                + shlex.quote(line)
                + " >> /etc/hosts"
            )
        return self.run("\n".join(script_parts))


def _have(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None


def suggest_local_mode() -> bool:
    """Heuristic: Ameyo/Asterisk paths exist → likely already on call server."""
    return Path("/etc/asterisk").exists() or Path("/usr/lib64/asterisk").exists()
