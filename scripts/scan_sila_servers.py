"""Scan the current network via SiLA mDNS discovery and list active servers.

Mirrors fastapi_app/app/routes/sila_discovery.py::_discover.
Uses SilaDiscoveryBrowser, which listens for SiLA servers advertising
themselves via zeroconf/mDNS on the local network.
"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from typing import Any

from sila2.client import SilaClient
from sila2.discovery import SilaDiscoveryBrowser


def _call_with_timeout(func, *, timeout_seconds: float, default):
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            result_queue.put(func())
        except Exception:
            result_queue.put(default)

    threading.Thread(target=_worker, daemon=True).start()
    try:
        return result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        return default


def scan(listen_seconds: float, insecure: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with SilaDiscoveryBrowser(insecure=insecure) as browser:
        if listen_seconds > 0:
            time.sleep(listen_seconds)
        for client in browser.clients:
            name = _call_with_timeout(
                lambda: client.SiLAService.ServerName.get(), timeout_seconds=2.0, default="unknown"
            )
            uuid = _call_with_timeout(
                lambda: client.SiLAService.ServerUUID.get(), timeout_seconds=2.0, default="unknown"
            )
            server_type = _call_with_timeout(
                lambda: client.SiLAService.ServerType.get(), timeout_seconds=2.0, default="unknown"
            )
            results.append(
                {
                    "ip": client.address,
                    "port": client.port,
                    "name": name,
                    "uuid": str(uuid),
                    "type": server_type,
                }
            )
    return results


def probe(ip: str, port: int, insecure: bool, timeout: float = 1.5) -> dict[str, Any] | None:
    """Direct TCP probe fallback: try to open a SilaClient at ip:port."""
    def _probe():
        with SilaClient(ip, port, insecure=insecure) as client:
            return {
                "ip": ip,
                "port": port,
                "name": client.SiLAService.ServerName.get(),
                "uuid": str(client.SiLAService.ServerUUID.get()),
                "type": client.SiLAService.ServerType.get(),
            }

    return _call_with_timeout(_probe, timeout_seconds=timeout, default=None)


def sweep(hosts: list[str], ports: list[int], insecure: bool) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for host in hosts:
        for port in ports:
            info = probe(host, port, insecure=insecure)
            if info is not None:
                hits.append(info)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=5.0, help="mDNS listen seconds (default 5)")
    parser.add_argument("--insecure", action="store_true", default=True)
    parser.add_argument(
        "--sweep",
        nargs="*",
        metavar="HOST",
        help="Fallback: also probe these hosts directly on --ports (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--ports",
        default="50052-50057",
        help="Port range/list for --sweep, e.g. '50052-50057' or '50052,50055' (default 50052-50057).",
    )
    args = parser.parse_args()

    def parse_ports(spec: str) -> list[int]:
        out: list[int] = []
        for part in spec.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                out.extend(range(int(a), int(b) + 1))
            elif part:
                out.append(int(part))
        return out

    print(f"Scanning via mDNS for {args.timeout}s ...", file=sys.stderr)
    found = scan(args.timeout, args.insecure)

    seen = {(s["ip"], s["port"]) for s in found}
    if args.sweep is not None:
        hosts = args.sweep or ["127.0.0.1"]
        ports = parse_ports(args.ports)
        print(f"Sweeping {len(hosts)} host(s) x {len(ports)} port(s) ...", file=sys.stderr)
        for s in sweep(hosts, ports, args.insecure):
            if (s["ip"], s["port"]) not in seen:
                seen.add((s["ip"], s["port"]))
                found.append(s)

    if not found:
        print("No SiLA servers found.")
        return 1

    print(f"\nFound {len(found)} SiLA server(s):")
    for s in found:
        print(f"  {s['ip']}:{s['port']}  name={s['name']!r}  type={s['type']!r}  uuid={s['uuid']}")
    print("\nIP addresses:")
    for ip in sorted({s["ip"] for s in found}):
        print(f"  {ip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
