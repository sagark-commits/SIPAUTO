"""SSH helper for remote apply / verify / reload."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import paramiko

from sipauto.models import SSHConfig


@dataclass
class SSHResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class SSHClient:
    def __init__(self, cfg: SSHConfig):
        self.cfg = cfg
        self._client: paramiko.SSHClient | None = None

    def __enter__(self) -> "SSHClient":
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = {
            "hostname": self.cfg.host,
            "port": self.cfg.port,
            "username": self.cfg.user,
            "timeout": self.cfg.connect_timeout,
            "allow_agent": True,
            "look_for_keys": True,
        }
        if self.cfg.key_path:
            kwargs["key_filename"] = str(Path(self.cfg.key_path).expanduser())
        if self.cfg.password:
            kwargs["password"] = self.cfg.password
        client.connect(**kwargs)
        self._client = client
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def run(self, command: str, timeout: int = 120) -> SSHResult:
        assert self._client is not None
        _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return SSHResult(exit_code=code, stdout=out, stderr=err)

    def write_file(self, remote_path: str, content: str, mode: int = 0o644) -> None:
        assert self._client is not None
        sftp = self._client.open_sftp()
        try:
            # backup if exists
            try:
                sftp.stat(remote_path)
                backup = remote_path + ".sipauto.bak"
                self.run(f"cp -a {remote_path} {backup}")
            except OSError:
                pass
            with sftp.file(remote_path, "w") as fh:
                fh.write(content)
            sftp.chmod(remote_path, mode)
        finally:
            sftp.close()

    def append_unique_hosts(self, entries: list[str]) -> SSHResult:
        """Append hosts lines if not already present."""
        script_parts = ["set -e"]
        for line in entries:
            ip, _, name = line.partition(" ")
            name = name.strip()
            script_parts.append(
                f"grep -qE '(^|\\s){name}(\\s|$)' /etc/hosts || echo '{line}' >> /etc/hosts"
            )
        return self.run("\n".join(script_parts))
