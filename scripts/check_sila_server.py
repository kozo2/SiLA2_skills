"""Check whether a SiLA server is reachable at a given IP and port.

Exit codes:
  0 — server is up and responded to SiLAService queries
  1 — connection or SiLA handshake failed
  2 — bad arguments
"""
from __future__ import annotations

import argparse
import ipaddress
import queue
import socket
import sys
import threading
import time
from typing import Any

from sila2.client import SilaClient


def _call_with_timeout(func, *, timeout_seconds: float, default):
    result_queue: queue.Queue = queue.Queue(maxsize=1)
    exc_box: list[BaseException] = []

    def _worker() -> None:
        try:
            result_queue.put(func())
        except BaseException as e:  # noqa: BLE001 — surface any failure
            exc_box.append(e)
            result_queue.put(default)

    threading.Thread(target=_worker, daemon=True).start()
    try:
        value = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        return default, TimeoutError(f"timed out after {timeout_seconds}s")
    return value, (exc_box[0] if exc_box else None)


def tcp_reachable(ip: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True, "tcp ok"
    except OSError as exc:
        return False, f"tcp failed: {exc}"


def check(ip: str, port: int, insecure: bool, timeout: float) -> dict[str, Any]:
    start = time.monotonic()
    ok_tcp, tcp_msg = tcp_reachable(ip, port, timeout)
    result: dict[str, Any] = {
        "ip": ip,
        "port": port,
        "tcp_reachable": ok_tcp,
        "tcp_detail": tcp_msg,
        "sila_reachable": False,
    }
    if not ok_tcp:
        result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
        return result

    def _probe() -> dict[str, Any]:
        with SilaClient(ip, port, insecure=insecure) as client:
            return {
                "name": client.SiLAService.ServerName.get(),
                "uuid": str(client.SiLAService.ServerUUID.get()),
                "type": client.SiLAService.ServerType.get(),
                "description": client.SiLAService.ServerDescription.get(),
                "vendor_url": client.SiLAService.ServerVendorURL.get(),
                "version": client.SiLAService.ServerVersion.get(),
                "features": [str(f) for f in client.SiLAService.ImplementedFeatures.get()],
            }

    info, err = _call_with_timeout(_probe, timeout_seconds=timeout, default=None)
    result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
    if info is None:
        result["error"] = f"{type(err).__name__}: {err}" if err else "unknown error"
        return result

    result["sila_reachable"] = True
    result.update(info)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", help="Server IPv4/IPv6 address or hostname")
    parser.add_argument("port", type=int, help="Server port (1-65535)")
    parser.add_argument("--timeout", type=float, default=3.0, help="Per-step timeout in seconds (default 3)")
    parser.add_argument("--insecure", action="store_true", default=True, help="Use insecure gRPC (default on)")
    parser.add_argument("--json", action="store_true", help="Emit a single JSON object")
    args = parser.parse_args()

    if not (1 <= args.port <= 65535):
        print(f"error: port {args.port} out of range 1-65535", file=sys.stderr)
        return 2

    ip = args.ip
    try:
        ip = str(ipaddress.ip_address(ip))
    except ValueError:
        try:
            ip = socket.gethostbyname(ip)
        except OSError as exc:
            print(f"error: could not resolve {args.ip!r}: {exc}", file=sys.stderr)
            return 2

    result = check(ip, args.port, insecure=args.insecure, timeout=args.timeout)

    if args.json:
        import json

        print(json.dumps(result, indent=2))
    else:
        status = "UP" if result["sila_reachable"] else "DOWN"
        print(f"[{status}] {ip}:{args.port}  ({result['elapsed_ms']} ms)")
        if result["sila_reachable"]:
            print(f"  name:        {result['name']}")
            print(f"  type:        {result['type']}")
            print(f"  uuid:        {result['uuid']}")
            print(f"  version:     {result['version']}")
            print(f"  vendor:      {result['vendor_url']}")
            print(f"  description: {result['description']}")
            print(f"  features:    {len(result['features'])}")
            for fid in result["features"]:
                print(f"    - {fid}")
        else:
            print(f"  tcp:   {result['tcp_detail']}")
            if "error" in result:
                print(f"  sila:  {result['error']}")

    return 0 if result["sila_reachable"] else 1


if __name__ == "__main__":
    sys.exit(main())
