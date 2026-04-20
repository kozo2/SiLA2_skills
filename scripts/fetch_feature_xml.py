"""Retrieve Feature XML from all SiLA2 servers started by docker-compose.

Mirrors fastapi_app/app/routes/sila_discovery.py::_get_feature_definitions.
Servers are exposed on localhost via the compose file (ports 50052-50057).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sila2.client import SilaClient

DEFAULT_TARGETS: list[tuple[str, int]] = [
    ("127.0.0.1", 50052),
    ("127.0.0.1", 50053),
    ("127.0.0.1", 50054),
    ("127.0.0.1", 50055),
    ("127.0.0.1", 50056),
    ("127.0.0.1", 50057),
]


def get_feature_definitions(ip: str, port: int, insecure: bool = True) -> dict[str, Any]:
    with SilaClient(ip, port, insecure=insecure) as client:
        feature_ids = list(client.SiLAService.ImplementedFeatures.get())
        features: list[dict[str, str]] = []
        for feature_id in feature_ids:
            xml = client.SiLAService.GetFeatureDefinition(feature_id).FeatureDefinition
            features.append({"feature_id": str(feature_id), "xml": xml})

        return {
            "name": client.SiLAService.ServerName.get(),
            "uuid": str(client.SiLAService.ServerUUID.get()),
            "type": client.SiLAService.ServerType.get(),
            "address": {"ip": ip, "port": port},
            "features": features,
            "count": len(features),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        metavar="IP:PORT",
        help="Override target(s); repeat flag for multiple. Default: localhost 50052-50057.",
    )
    parser.add_argument("--insecure", action="store_true", default=True)
    parser.add_argument(
        "--full-xml",
        action="store_true",
        help="Print full Feature XML instead of a preview.",
    )
    args = parser.parse_args()

    if args.target:
        targets = [(t.split(":")[0], int(t.split(":")[1])) for t in args.target]
    else:
        targets = DEFAULT_TARGETS

    results: list[dict[str, Any]] = []
    exit_code = 0
    for ip, port in targets:
        try:
            result = get_feature_definitions(ip, port, insecure=args.insecure)
            results.append(result)
            print(
                f"[OK] {ip}:{port}  name={result['name']!r}  type={result['type']!r}  "
                f"features={result['count']}"
            )
            for feat in result["features"]:
                if args.full_xml:
                    print(f"  --- {feat['feature_id']} ---")
                    print(feat["xml"])
                else:
                    preview = feat["xml"].strip().splitlines()[0][:100]
                    print(f"  - {feat['feature_id']}  ({len(feat['xml'])} chars)  {preview!r}")
        except Exception as exc:
            exit_code = 1
            print(f"[FAIL] {ip}:{port}  {type(exc).__name__}: {exc}", file=sys.stderr)

    summary = {
        "target_count": len(targets),
        "success_count": len(results),
        "servers": results,
    }
    with open("/tmp/sila_feature_xml.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote full JSON to /tmp/sila_feature_xml.json", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
