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

## Typical workflow

1. `scan_sila_servers.py` — find which servers are live on the network.
2. `check_sila_server.py <ip> <port>` — confirm a specific server is reachable.
3. `list_operations.py <ip> <port>` — see what commands/properties it exposes.
4. `fetch_feature_xml.py` — dump the raw Feature XML for offline inspection.
