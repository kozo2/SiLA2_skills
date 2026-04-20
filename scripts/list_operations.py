"""Fetch Feature XML from a SiLA server and list its executable device operations.

An "executable device operation" is a Command or Property defined in a non-core
feature (anything except org.silastandard/core/SiLAService).
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
from typing import Any
from xml.etree import ElementTree as ET

from sila2.client import SilaClient

NS = {"s": "http://www.sila-standard.org"}
CORE_SILASERVICE_PREFIX = "org.silastandard/core/SiLAService"


def fetch_feature_definitions(ip: str, port: int, insecure: bool) -> dict[str, Any]:
    with SilaClient(ip, port, insecure=insecure) as client:
        feature_ids = [str(f) for f in client.SiLAService.ImplementedFeatures.get()]
        features = [
            {
                "feature_id": fid,
                "xml": client.SiLAService.GetFeatureDefinition(fid).FeatureDefinition,
            }
            for fid in feature_ids
        ]
        return {
            "name": client.SiLAService.ServerName.get(),
            "uuid": str(client.SiLAService.ServerUUID.get()),
            "type": client.SiLAService.ServerType.get(),
            "address": {"ip": ip, "port": port},
            "features": features,
        }


def parse_operations(xml_text: str) -> dict[str, list[dict[str, Any]]]:
    root = ET.fromstring(xml_text)
    commands: list[dict[str, Any]] = []
    for cmd in root.findall("s:Command", NS):
        ident = cmd.findtext("s:Identifier", "", NS)
        display = cmd.findtext("s:DisplayName", "", NS)
        observable = cmd.findtext("s:Observable", "No", NS) == "Yes"
        params = [
            {
                "name": p.findtext("s:Identifier", "", NS),
                "display": p.findtext("s:DisplayName", "", NS),
            }
            for p in cmd.findall("s:Parameter", NS)
        ]
        returns = [
            r.findtext("s:Identifier", "", NS) for r in cmd.findall("s:Response", NS)
        ]
        commands.append(
            {
                "identifier": ident,
                "display_name": display,
                "observable": observable,
                "parameters": params,
                "responses": returns,
            }
        )

    properties: list[dict[str, Any]] = []
    for prop in root.findall("s:Property", NS):
        properties.append(
            {
                "identifier": prop.findtext("s:Identifier", "", NS),
                "display_name": prop.findtext("s:DisplayName", "", NS),
                "observable": prop.findtext("s:Observable", "No", NS) == "Yes",
            }
        )

    return {"commands": commands, "properties": properties}


def collect_operations(info: dict[str, Any], include_core: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for feat in info["features"]:
        fid = feat["feature_id"]
        if not include_core and fid.startswith(CORE_SILASERVICE_PREFIX):
            continue
        ops = parse_operations(feat["xml"])
        out.append({"feature_id": fid, **ops})
    return out


def print_human(info: dict[str, Any], by_feature: list[dict[str, Any]]) -> None:
    addr = info["address"]
    print(f"=== {info['name']}  ({info['type']})  @ {addr['ip']}:{addr['port']} ===")
    print(f"UUID: {info['uuid']}")
    if not by_feature:
        print("(no device features — only core SiLAService present)")
        return
    for feat in by_feature:
        print(f"\nFeature: {feat['feature_id']}")
        if feat["commands"]:
            print("  Commands (executable):")
            for c in feat["commands"]:
                params = ", ".join(p["name"] for p in c["parameters"])
                tag = " [observable]" if c["observable"] else ""
                returns = f" -> {', '.join(c['responses'])}" if c["responses"] else ""
                print(f"    - {c['identifier']}({params}){returns}{tag}")
        else:
            print("  Commands (executable): (none)")
        if feat["properties"]:
            print("  Properties (readable):")
            for p in feat["properties"]:
                tag = " [observable]" if p["observable"] else ""
                print(f"    - {p['identifier']}{tag}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", help="SiLA server IPv4/IPv6 address or hostname")
    parser.add_argument("port", type=int, help="SiLA server port (1-65535)")
    parser.add_argument("--insecure", action="store_true", default=True)
    parser.add_argument(
        "--include-core",
        action="store_true",
        help="Also list the core SiLAService feature (skipped by default).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human output.")
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

    try:
        info = fetch_feature_definitions(ip, args.port, insecure=args.insecure)
    except Exception as exc:
        print(f"error: could not fetch features from {ip}:{args.port}: {exc}", file=sys.stderr)
        return 1

    by_feature = collect_operations(info, include_core=args.include_core)

    if args.json:
        print(
            json.dumps(
                {
                    "server": {k: v for k, v in info.items() if k != "features"},
                    "features": by_feature,
                },
                indent=2,
            )
        )
    else:
        print_human(info, by_feature)

    return 0


if __name__ == "__main__":
    sys.exit(main())
