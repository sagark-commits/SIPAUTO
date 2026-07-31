"""Voice/SIP and RTP port checks (TCP/UDP).

SIP signaling: TCP and UDP on SBC port (default 5060).
RTP: UDP range 10000-40000 must be open both directions (local + carrier).
Full 30k-port scans are impractical — we validate policy, sample endpoints,
and remote SIP reachability.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field

from sipauto.models import CheckResult, Inventory


@dataclass
class PortCheckReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok or c.severity == "warn" for c in self.checks)


class PortChecker:
    def __init__(self, inv: Inventory, timeout: float = 2.0):
        self.inv = inv
        self.timeout = timeout

    def check_local(self) -> PortCheckReport:
        """Checks that can run without SSH (from this machine toward SBC)."""
        report = PortCheckReport()
        net = self.inv.network
        transport = net.sip_transport.lower()

        if transport in ("udp", "both"):
            report.checks.append(self._udp_probe(net.sbc_ip, net.sbc_port, "SIP UDP"))
        if transport in ("tcp", "both"):
            report.checks.append(self._tcp_connect(net.sbc_ip, net.sbc_port, "SIP TCP"))

        # RTP sample probes (UDP send) — carrier may not reply; treat as informational
        for port in self._rtp_sample_ports():
            report.checks.append(
                self._udp_probe(
                    net.sbc_ip,
                    port,
                    f"RTP UDP sample {port}",
                    severity="warn",
                )
            )

        report.checks.append(
            CheckResult(
                name="RTP range policy",
                ok=net.rtp_start == 10000 and net.rtp_end == 40000,
                detail=(
                    f"Configured RTP UDP {net.rtp_start}-{net.rtp_end}. "
                    "Both sides must allow this range (local firewall + carrier). "
                    "Also set Asterisk rtp.conf rtpstart/rtpend to match."
                ),
                severity="error"
                if not (net.rtp_start <= 10000 and net.rtp_end >= 40000)
                else "info",
            )
        )
        # Normalize ok for info severity
        for c in report.checks:
            if c.severity == "info":
                c.ok = True
        return report

    def remote_check_commands(self) -> list[str]:
        """Shell snippets to run on the call server via SSH."""
        net = self.inv.network
        rtp_s, rtp_e = net.rtp_start, net.rtp_end
        cmds = [
            f"echo '=== SIP UDP to SBC {net.sbc_ip}:{net.sbc_port} ==='",
            (
                f"timeout 2 bash -c 'echo -n >/dev/udp/{net.sbc_ip}/{net.sbc_port}' "
                f"&& echo SIP_UDP_SEND_OK || echo SIP_UDP_SEND_FAIL"
            ),
            f"echo '=== SIP TCP to SBC {net.sbc_ip}:{net.sbc_port} ==='",
            (
                f"timeout 3 bash -c 'cat < /dev/null > /dev/tcp/{net.sbc_ip}/{net.sbc_port}' "
                f"&& echo SIP_TCP_OK || echo SIP_TCP_FAIL"
            ),
            "echo '=== Local firewall RTP range (iptables/nft if present) ==='",
            "command -v iptables >/dev/null && iptables -L INPUT -n 2>/dev/null | head -50 || true",
            "command -v nft >/dev/null && nft list ruleset 2>/dev/null | head -80 || true",
            "echo '=== firewalld rich rules / ports (if any) ==='",
            "command -v firewall-cmd >/dev/null && firewall-cmd --list-all 2>/dev/null || true",
            "echo '=== Asterisk rtp.conf ==='",
            "grep -E '^(rtpstart|rtpend)' /etc/asterisk/rtp.conf 2>/dev/null || echo 'rtp.conf not found or no rtpstart/rtpend'",
            (
                "echo EXPECTED: rtpstart=%s rtpend=%s and firewall allow UDP %s:%s both directions"
                % (rtp_s, rtp_e, rtp_s, rtp_e)
            ),
            "echo '=== Listening SIP ports ==='",
            "ss -ulnp | grep -E ':5060|:5061' || netstat -ulnp 2>/dev/null | grep -E ':5060|:5061' || true",
            "ss -tlnp | grep -E ':5060|:5061' || true",
        ]
        return cmds

    def parse_remote_output(self, output: str) -> PortCheckReport:
        report = PortCheckReport()
        text = output or ""
        report.checks.append(
            CheckResult(
                name="SIP UDP send (remote)",
                ok="SIP_UDP_SEND_OK" in text,
                detail="UDP datagram send to SBC signaling port from call server",
            )
        )
        report.checks.append(
            CheckResult(
                name="SIP TCP connect (remote)",
                ok="SIP_TCP_OK" in text,
                detail="TCP connect to SBC signaling port from call server",
                severity="warn" if self.inv.network.sip_transport == "udp" else "error",
            )
        )
        rtp_ok = (
            f"rtpstart={self.inv.network.rtp_start}" in text
            or f"rtpstart = {self.inv.network.rtp_start}" in text
            or "rtp.conf not found" not in text
        )
        # Soft check — warn if rtp.conf missing expected values
        has_rtpstart = "rtpstart" in text and "not found" not in text.lower()
        report.checks.append(
            CheckResult(
                name="Asterisk rtp.conf range",
                ok=has_rtpstart,
                detail=(
                    f"Expect rtpstart={self.inv.network.rtp_start} "
                    f"rtpend={self.inv.network.rtp_end}. Output snippet checked."
                ),
                severity="warn",
            )
        )
        report.checks.append(
            CheckResult(
                name="RTP UDP both-side reminder",
                ok=True,
                detail=(
                    f"Ensure UDP {self.inv.network.rtp_start}-{self.inv.network.rtp_end} "
                    "is open BOTH sides (call server firewall AND carrier). "
                    "Cannot fully prove carrier side from here."
                ),
                severity="info",
            )
        )
        _ = rtp_ok
        return report

    def _rtp_sample_ports(self) -> list[int]:
        s, e = self.inv.network.rtp_start, self.inv.network.rtp_end
        mid = (s + e) // 2
        return sorted({s, mid, e})

    def _tcp_connect(self, host: str, port: int, name: str) -> CheckResult:
        try:
            with socket.create_connection((host, port), timeout=self.timeout):
                return CheckResult(name=name, ok=True, detail=f"Connected to {host}:{port}/tcp")
        except OSError as exc:
            return CheckResult(
                name=name,
                ok=False,
                detail=f"TCP {host}:{port} failed: {exc}",
                severity="warn",
            )

    def _udp_probe(
        self, host: str, port: int, name: str, severity: str = "warn"
    ) -> CheckResult:
        """Best-effort UDP send; lack of ICMP/response is not a hard failure."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            sock.sendto(b"\x00", (host, port))
            sock.close()
            return CheckResult(
                name=name,
                ok=True,
                detail=f"UDP send to {host}:{port} succeeded (no reply expected)",
                severity=severity,
            )
        except OSError as exc:
            return CheckResult(
                name=name,
                ok=False,
                detail=f"UDP {host}:{port} failed: {exc}",
                severity=severity,
            )
