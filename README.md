# SiLA2 Utility Scripts

Small standalone Python scripts for interacting with the SiLA2 servers launched
by the repo's `docker-compose.yml`. All connect with `insecure=True` to match
the servers, which are started with `--insecure`.

Run any script with `uv`:

```sh
uv run python scripts/<script>.py [args...]
```

## scan_sila_servers.py

Scans the current network via SiLA mDNS discovery (`SilaDiscoveryBrowser`) and
lists each reachable server's IP, port, name, type, and UUID. Useful for
discovering which SiLA servers are live without knowing their addresses ahead
of time.

```sh
# 5-second mDNS listen (default)
uv run python scripts/scan_sila_servers.py

# Longer listen window
uv run python scripts/scan_sila_servers.py --timeout 10

# Fallback: also probe specific hosts/ports directly (useful if mDNS is blocked)
uv run python scripts/scan_sila_servers.py --sweep 127.0.0.1 --ports 50052-50057
```

## check_sila_server.py

Checks whether a SiLA server is reachable at a specific `<ip> <port>`. Runs a
two-stage probe: (1) TCP connect, (2) SiLA handshake reading `SiLAService`
metadata (name, type, UUID, version, vendor, description, implemented
features). Exits `0` if the server is up, `1` if down.

```sh
uv run python scripts/check_sila_server.py 127.0.0.1 50052

# JSON output
uv run python scripts/check_sila_server.py 127.0.0.1 50052 --json

# Custom timeout (seconds)
uv run python scripts/check_sila_server.py 127.0.0.1 50052 --timeout 5
```

## fetch_feature_xml.py

Retrieves the Feature Definition XML for every feature implemented by each
target server (defaults to `127.0.0.1:50052-50057`, the ports exposed by the
compose file). Prints a per-feature summary to stdout and writes the full
payload to `/tmp/sila_feature_xml.json`.

```sh
# All compose targets
uv run python scripts/fetch_feature_xml.py

# Single target
uv run python scripts/fetch_feature_xml.py --target 127.0.0.1:50052

# Print the full XML (not just a preview) for each feature
uv run python scripts/fetch_feature_xml.py --full-xml
```

## list_operations.py

Fetches the Feature XML from one SiLA server and lists its executable device
operations — Commands (with parameters and responses) and readable
Properties — parsed from each non-core feature. The core
`org.silastandard/core/SiLAService` feature is skipped by default.

```sh
uv run python scripts/list_operations.py 127.0.0.1 50052

# Include the core SiLAService feature
uv run python scripts/list_operations.py 127.0.0.1 50052 --include-core

# JSON output
uv run python scripts/list_operations.py 127.0.0.1 50052 --json
```

## run_protocol.py

Executes a demo plate-processing protocol that chains commands from four of
the docker-compose servers, using the Commands identified by
`list_operations.py`:

1. **Seal** — `PlateLocController.StartCycle`
2. **Thermal run** — `AutomatedThermalCyclerController.Load` → `Validate`
   → `CloseLid` → `StartRun`
3. **Centrifuge** — `MicroplateCentrifugeController.SpinCycle`
4. **Peel** — `AutomatedPlateSealRemoverController.Peel`

Endpoints default to the compose ports (`plateloc=50053`,
`thermal-cycler=50055`, `centrifuge=50052`, `seal-remover=50054` on
`127.0.0.1`); each is overridable with `--<role> host:port`.

```sh
# Run with defaults
uv run python scripts/run_protocol.py

# Override endpoints and tune parameters
uv run python scripts/run_protocol.py \
  --plateloc 127.0.0.1:50053 \
  --thermal-cycler 127.0.0.1:50055 \
  --centrifuge 127.0.0.1:50052 \
  --seal-remover 127.0.0.1:50054 \
  --spin-time 60 --spin-velocity 90 \
  --peel-location 3 --adhesion-time 3
```

Known mock-server caveat: every observable command's `finally` calls a
non-existent `instance.complete()`, which makes the client's `get_responses()`
raise. The script polls `instance.done` instead and tolerates a terminal
`finishedWithError` status — side effects still run, so each step logs
`status=finishedWithError` but the protocol advances correctly. By the same
token, `SetSealingTemperature` / `SetSealingTime` are skipped by default
(enable with `--configure-sealing` if the server is fixed).

## Typical workflow

1. `scan_sila_servers.py` — find which servers are live on the network.
2. `check_sila_server.py <ip> <port>` — confirm a specific server is reachable.
3. `list_operations.py <ip> <port>` — see what commands/properties it exposes.
4. `fetch_feature_xml.py` — dump the raw Feature XML for offline inspection.
5. `run_protocol.py` — chain those commands into an end-to-end protocol.
