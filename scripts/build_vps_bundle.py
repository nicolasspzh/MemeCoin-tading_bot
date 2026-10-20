"""Package allowlisted source and the frozen protocol, never runtime credentials."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[1]


def build(output, protocol=True):
    files = {name: (ROOT / name).read_bytes() for name in
             ("README.md", "requirements.txt", "pyproject.toml", "main.py", ".env.example", ".gitignore")}
    for folder in ("backtesting", "collectors", "config", "data", "trading", "operations", "tests"):
        for path in (ROOT / folder).glob("*.py"):
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for folder, pattern in (("tests/fixtures", "*.json"), ("deploy", "*.py"), ("deploy", "*.sh"),
                            ("deploy", "*.service"), ("deploy", "*.timer"), ("deploy", "*.md"), ("deploy", "*.json"), ("scripts", "*.py"), ("scripts", "*.sh")):
        for path in (ROOT / folder).glob(pattern):
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    release = ROOT / 'deploy/release.json'
    folder = (str(Path(json.loads(release.read_text())['protocol']).parent) + '/'
              if release.exists() else 'runtime/backtests/phase6-protocol-20261007/')
    # A probe without test character carries no frozen protocol.
    # A reference protocol (version 2) binds external evidence and has no frozen copy.
    for name in ("protocol.json", "development.sqlite3") if protocol else ():
        if name == "protocol.json" or (ROOT / folder / name).exists():
            files[folder + name] = (ROOT / folder / name).read_bytes()
    # Compare actual configured secret values without putting any in output.
    from config.settings import load_settings
    from urllib.parse import parse_qs, urlsplit
    settings = load_settings()
    values = [value.encode() for endpoint in (settings.solana_rpc_url, *settings.solana_rpc_fallback_urls)
              for values in parse_qs(urlsplit(endpoint).query).values() for value in values if len(value) >= 8]
    if any(secret in content for secret in values for content in files.values()):
        raise ValueError("Configured credential unexpectedly present in package inputs")
    sums = "".join(f"{hashlib.sha256(value).hexdigest()}  {name}\n" for name, value in sorted(files.items()))
    files["SHA256SUMS"] = sums.encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Do not silently overwrite a package that the user may already be installing.
    with output.open("xb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, value in sorted(files.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(value), 0o644, 0
                archive.addfile(info, io.BytesIO(value))
    return {"path": str(output), "bytes": output.stat().st_size, "files": len(files),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-protocol", action="store_true", help="Probe bundle without a frozen protocol")
    args = parser.parse_args()
    print(json.dumps(build(args.out.resolve(), protocol=not args.no_protocol), indent=2))
