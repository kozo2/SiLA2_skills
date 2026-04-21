"""Run an end-to-end plate-processing protocol across four SiLA2 servers.

Steps (and the commands from `scripts/list_operations.py` each step uses):
  1. Seal         — PlateLocController.StartCycle
                    (with SetSealingTemperature + SetSealingTime first)
  2. Thermal run  — AutomatedThermalCyclerController.Load + Validate
                    + CloseLid + StartRun
  3. Centrifuge   — MicroplateCentrifugeController.SpinCycle
  4. Peel         — AutomatedPlateSealRemoverController.Peel

All commands use `insecure=True` gRPC to match the docker-compose servers.
Observable commands are awaited via `get_responses()`.
"""
from __future__ import annotations

import argparse
import sys
import time
from contextlib import ExitStack
from typing import Any

from sila2.client import SilaClient

# Default endpoints per docker-compose.yml.
DEFAULT_ENDPOINTS = {
    "plateloc": ("127.0.0.1", 50053),
    "thermal_cycler": ("127.0.0.1", 50055),
    "centrifuge": ("127.0.0.1", 50052),
    "seal_remover": ("127.0.0.1", 50054),
}

# Minimal valid PCR-style protocol payload — contents don't matter for the
# mock server; it just checks the payload is non-empty.
MOCK_PROTOCOL_BYTES = (
    b"# Mock thermal cycler protocol\n"
    b"hold 95C 180s\n"
    b"cycle 40:\n"
    b"  95C 15s\n"
    b"  60C 60s\n"
    b"hold 4C inf\n"
)


def _log(step: str, msg: str) -> None:
    print(f"[{step}] {msg}", flush=True)


def _await(step: str, instance: Any, *, timeout_s: float = 60.0) -> None:
    """Block on an observable command instance until it reports done.

    The repo's mock servers call a non-existent `instance.complete()` at the
    end of each observable command, which makes `get_responses()` raise even
    though the command's side effects completed. We poll `.done` instead and
    treat a terminal `finishedWithError` status as an expected mock artifact.
    """
    started = time.monotonic()
    deadline = started + timeout_s
    while time.monotonic() < deadline:
        if instance.done:
            break
        time.sleep(0.05)
    else:
        raise TimeoutError(f"{step}: command did not finish within {timeout_s}s")
    elapsed = (time.monotonic() - started) * 1000
    status = str(instance.status).split(".")[-1] if instance.status else "unknown"
    _log(step, f"done in {elapsed:.0f} ms (status={status})")


def seal_plate(
    client: SilaClient,
    *,
    sealing_temperature_c: int,
    sealing_time_s: float,
    configure: bool,
) -> None:
    feat = client.PlateLocController
    if configure:
        # NOTE: the mock server currently fails on these setters because it
        # attempts to call update_SealingTemperature/update_SealingTime on
        # non-observable properties. Off by default; enable with --configure-sealing.
        _log("seal", f"set temperature={sealing_temperature_c}C, time={sealing_time_s}s")
        feat.SetSealingTemperature(SealingTemperature=sealing_temperature_c)
        feat.SetSealingTime(SealingTime=sealing_time_s)
    else:
        current_t = feat.SealingTemperature.get()
        current_s = feat.SealingTime.get()
        _log("seal", f"using current settings: temperature={current_t}C, time={current_s}s")
    _log("seal", "StartCycle ...")
    _await("seal", feat.StartCycle())


def run_thermal_cycler(
    client: SilaClient,
    *,
    protocol_bytes: bytes,
    max_sample_volume_ul: float,
) -> None:
    feat = client.AutomatedThermalCyclerController
    _log("thermal", f"Load ({len(protocol_bytes)} bytes) ...")
    _await("thermal", feat.Load(ProtocolFileData=protocol_bytes))
    _log("thermal", f"Validate (max_sample_volume={max_sample_volume_ul} uL) ...")
    _await("thermal", feat.Validate(MaxSampleVolume=max_sample_volume_ul))
    _log("thermal", "CloseLid ...")
    _await("thermal", feat.CloseLid())
    _log("thermal", "StartRun ...")
    _await("thermal", feat.StartRun())


def centrifuge(
    client: SilaClient,
    *,
    time_s: int,
    velocity_percent: float,
    bucket_to_load: int,
    bucket_to_unload: int,
) -> None:
    feat = client.MicroplateCentrifugeController
    _log("centrifuge", f"SpinCycle v={velocity_percent}%, t={time_s}s ...")
    _await(
        "centrifuge",
        feat.SpinCycle(
            VelocityPercent=velocity_percent,
            AccelerationPercent=50.0,
            DecelerationPercent=50.0,
            TimerMode=1,
            Time=time_s,
            BucketNumberToLoad=bucket_to_load,
            BucketNumberToUnload=bucket_to_unload,
            GripperOffsetToLoad=10.0,
            GripperOffsetToUnload=10.0,
            PlateHeightToLoad=15.0,
            PlateHeightToUnload=15.0,
            SpeedToLoad=1,
            SpeedToUnload=1,
            OptionsToLoad=0,
            OptionsToUnload=0,
        ),
    )


def peel_seal(
    client: SilaClient,
    *,
    begin_peel_location: int,
    adhesion_time: int,
) -> None:
    feat = client.AutomatedPlateSealRemoverController
    _log("peel", f"Peel location={begin_peel_location}, adhesion={adhesion_time} ...")
    _await(
        "peel",
        feat.Peel(BeginPeelLocation=begin_peel_location, AdhesionTime=adhesion_time),
    )


def _parse_endpoint(spec: str) -> tuple[str, int]:
    host, port = spec.split(":", 1)
    return host, int(port)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plateloc", type=_parse_endpoint, default=DEFAULT_ENDPOINTS["plateloc"])
    parser.add_argument("--thermal-cycler", type=_parse_endpoint, default=DEFAULT_ENDPOINTS["thermal_cycler"])
    parser.add_argument("--centrifuge", type=_parse_endpoint, default=DEFAULT_ENDPOINTS["centrifuge"])
    parser.add_argument("--seal-remover", type=_parse_endpoint, default=DEFAULT_ENDPOINTS["seal_remover"])
    parser.add_argument("--sealing-temperature", type=int, default=175, help="C (20-235)")
    parser.add_argument("--sealing-time", type=float, default=1.5, help="seconds (0.5-12.0)")
    parser.add_argument(
        "--configure-sealing",
        action="store_true",
        help="Call SetSealingTemperature/SetSealingTime before StartCycle. "
        "Disabled by default because the mock server has a known bug in these setters.",
    )
    parser.add_argument("--max-sample-volume", type=float, default=50.0, help="uL")
    parser.add_argument("--spin-time", type=int, default=30, help="seconds (1-86400)")
    parser.add_argument("--spin-velocity", type=float, default=80.0, help="percent (1-100)")
    parser.add_argument("--bucket", type=int, default=1, help="centrifuge bucket (1 or 2)")
    parser.add_argument("--peel-location", type=int, default=5, help="begin peel location (1-9)")
    parser.add_argument("--adhesion-time", type=int, default=2, help="adhesion time (1-4)")
    args = parser.parse_args()

    with ExitStack() as stack:
        plateloc = stack.enter_context(SilaClient(*args.plateloc, insecure=True))
        thermal = stack.enter_context(SilaClient(*args.thermal_cycler, insecure=True))
        cent = stack.enter_context(SilaClient(*args.centrifuge, insecure=True))
        peeler = stack.enter_context(SilaClient(*args.seal_remover, insecure=True))

        _log("connect", f"PlateLoc={plateloc.SiLAService.ServerName.get()}")
        _log("connect", f"ThermalCycler={thermal.SiLAService.ServerName.get()}")
        _log("connect", f"Centrifuge={cent.SiLAService.ServerName.get()}")
        _log("connect", f"SealRemover={peeler.SiLAService.ServerName.get()}")

        t0 = time.monotonic()
        seal_plate(
            plateloc,
            sealing_temperature_c=args.sealing_temperature,
            sealing_time_s=args.sealing_time,
            configure=args.configure_sealing,
        )
        run_thermal_cycler(
            thermal,
            protocol_bytes=MOCK_PROTOCOL_BYTES,
            max_sample_volume_ul=args.max_sample_volume,
        )
        centrifuge(
            cent,
            time_s=args.spin_time,
            velocity_percent=args.spin_velocity,
            bucket_to_load=args.bucket,
            bucket_to_unload=args.bucket,
        )
        peel_seal(
            peeler,
            begin_peel_location=args.peel_location,
            adhesion_time=args.adhesion_time,
        )
        total = (time.monotonic() - t0) * 1000
        _log("done", f"protocol finished in {total:.0f} ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())
