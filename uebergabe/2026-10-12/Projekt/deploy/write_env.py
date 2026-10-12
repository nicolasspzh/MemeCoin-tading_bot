"""Read a credential from the terminal without echo; write a root-only env file."""
import getpass
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit


def write_env(path, value):
    url = urlsplit(value)
    keys = parse_qs(url.query).get("api-key", [])
    if (url.scheme != "https" or url.hostname != "mainnet.helius-rpc.com"
            or url.username or url.password or not keys or not keys[0]
            or any(c.isspace() or ord(c) < 32 or c in "\"'\\*" for c in value)):
        raise ValueError("Invalid Helius RPC URL")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write("MODE=PAPER\nSOLANA_RPC_URL=" + value + "\n")


if __name__ == "__main__":
    try:
        if not sys.stdin.isatty():
            raise ValueError("An interactive SSH terminal is required")
        value = getpass.getpass("Vollständige Helius-RPC-URL einfügen (Eingabe bleibt unsichtbar): ").strip()
        write_env(Path(sys.argv[1]), value)
    except Exception as error:
        print(f"RPC-Konfiguration fehlgeschlagen: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)
