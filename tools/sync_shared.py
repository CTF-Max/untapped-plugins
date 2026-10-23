"""Copy shared Python modules into plugin server directories.

Each plugin gets mcp_stdio.py; a plugin that needs more lists them, one file name per line, in `<plugin>/SHARED`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT = ["mcp_stdio.py"]


def wanted(plugin: Path) -> list[str]:
    listing = plugin / "SHARED"
    if not listing.is_file():
        return DEFAULT
    names = [line.strip() for line in listing.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(set(DEFAULT + names))


def sync(root: Path, check: bool = False) -> int:
    shared = root / "shared"
    # A plugin is the folder holding a manifest dir with plugin.json; the lane root's .claude-plugin/ holds only
    # marketplace.json, so it is not a plugin.
    plugin_dirs = sorted({marker.parent.parent for name in (".codex-plugin", ".claude-plugin")
                          for marker in root.rglob(name + "/plugin.json")})
    drift: list[str] = []
    for plugin in plugin_dirs:
        server = plugin / "server"
        if not server.is_dir():  # skills-only plugin (chatgpt/): no server, nothing shared
            continue
        for name in wanted(plugin):
            source, target = shared / name, server / name
            if not source.is_file():
                print(f"{plugin.name}/SHARED names a missing module: {name}", file=sys.stderr)
                return 1
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                drift.append(str(target.relative_to(root)))
                if not check:
                    server.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())

    if check:
        if drift:
            print("Shared copies out of date: " + ", ".join(drift))
            return 1
        print(f"Shared copies current ({len(plugin_dirs)} plugin(s)).")
        return 0
    print(f"Synced shared modules to {len(plugin_dirs)} plugin(s); updated {len(drift)} file(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift without writing files")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="plugins directory (defaults to this script's parent)")
    args = parser.parse_args()
    return sync(args.root.resolve(), args.check)


if __name__ == "__main__":
    raise SystemExit(main())
