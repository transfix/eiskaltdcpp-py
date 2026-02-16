#!/usr/bin/env python3
"""
Example: Manage shared directories and monitor file hashing.

Demonstrates:
  - Adding and removing shared directories
  - Listing current shares with sizes
  - Refreshing file lists
  - Monitoring hash progress
  - Pausing and resuming hashing

Usage:
    python share_manager.py [--config-dir DIR]

Interactive commands let you manage shares without connecting to a hub.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from eiskaltdcpp import DCClient


def format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def show_shares(client: DCClient) -> None:
    """Display current share configuration."""
    shares = client.list_shares()
    total = client.share_size
    count = client.shared_files

    print(f"\n{'=' * 60}")
    print(f"  SHARED DIRECTORIES ({len(shares)} dirs, {count} files, "
          f"{format_size(total)} total)")
    print(f"{'=' * 60}")

    if not shares:
        print("  No directories shared")
    else:
        for s in shares:
            print(f"  [{s.virtualName}]  →  {s.realPath}")

    print()


def show_hash_status(client: DCClient) -> None:
    """Display current hashing status."""
    hs = client.hash_status
    if hs.filesLeft > 0:
        print(f"  Hashing: {hs.filesLeft} files remaining "
              f"({format_size(hs.bytesLeft)} bytes)")
        if hs.currentFile:
            print(f"  Current: {hs.currentFile}")
    else:
        print("  Hashing: idle (all files hashed)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage DC shared directories")
    parser.add_argument("--config-dir", default="",
                        help="Config directory (default: ~/.eiskaltdcpp-py/)")
    args = parser.parse_args()

    client = DCClient(args.config_dir)
    if not client.initialize():
        print("ERROR: Failed to initialize DC core", file=sys.stderr)
        sys.exit(1)

    # ─── Hash progress callback ───

    @client.on("hash_progress")
    def on_hash(current_file: str, files_left: int, bytes_left: int) -> None:
        if files_left > 0 and files_left % 100 == 0:
            print(f"  [hash] {files_left} files remaining "
                  f"({format_size(bytes_left)})")

    # ─── Interactive loop ───

    print("Share Manager — manage your DC shared directories")
    print()

    show_shares(client)

    while True:
        print("Commands:")
        print("  add <path> <name>  — Share a directory with a virtual name")
        print("  remove <path>      — Unshare a directory")
        print("  rename <path> <n>  — Rename a share's virtual name")
        print("  list               — Show current shares")
        print("  refresh            — Refresh shared file lists")
        print("  hash               — Show hashing progress")
        print("  pause              — Pause file hashing")
        print("  resume             — Resume file hashing")
        print("  stats              — Show share statistics")
        print("  quit               — Exit")
        print()

        try:
            cmd = input("share> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue

        parts = cmd.split(maxsplit=2)
        action = parts[0].lower()

        if action == "quit" or action == "q":
            break

        elif action == "add":
            if len(parts) >= 3:
                path, name = parts[1], parts[2]
                ok = client.add_share(path, name)
                if ok:
                    print(f"  Added: {path} as [{name}]")
                else:
                    print(f"  Failed to add: {path}")
                    print("  (directory must exist and not overlap existing shares)")
            else:
                print("  Usage: add <path> <virtual_name>")
                print("  Example: add /home/user/music Music")

        elif action == "remove":
            if len(parts) >= 2:
                path = parts[1]
                ok = client.remove_share(path)
                if ok:
                    print(f"  Removed: {path}")
                else:
                    print(f"  Failed to remove: {path}")
            else:
                print("  Usage: remove <path>")

        elif action == "rename":
            if len(parts) >= 3:
                path, new_name = parts[1], parts[2]
                ok = client.rename_share(path, new_name)
                if ok:
                    print(f"  Renamed: {path} → [{new_name}]")
                else:
                    print(f"  Failed to rename: {path}")
            else:
                print("  Usage: rename <path> <new_name>")

        elif action == "list":
            show_shares(client)

        elif action == "refresh":
            print("  Refreshing shared file lists...")
            client.refresh_share()
            print("  Refresh started (hashing may take a while)")

        elif action == "hash":
            show_hash_status(client)

        elif action == "pause":
            client.pause_hashing(True)
            print("  Hashing paused")

        elif action == "resume":
            client.pause_hashing(False)
            print("  Hashing resumed")

        elif action == "stats":
            total = client.share_size
            count = client.shared_files
            print(f"  Total share: {format_size(total)}")
            print(f"  Total files: {count}")
            print(f"  Version: {client.version}")
            show_hash_status(client)

        else:
            print(f"  Unknown command: {action}")

        print()

    client.shutdown()
    print("[*] Bye!")


if __name__ == "__main__":
    main()
