#!/usr/bin/env python3
"""
Example: Request, browse, and download from a user's file list.

Demonstrates:
  - Connecting to a hub
  - Requesting a user's file list
  - Browsing the file list directory structure
  - Downloading individual files or entire directories from the list
  - Managing file list lifecycle (open/close)

Usage:
    python file_list_browser.py dchub://hub.example.com:411 SomeUserNick

Press Ctrl+C to quit.
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


def browse_interactive(client: DCClient, file_list_id: str) -> None:
    """Interactive file list browser."""
    cwd = "/"

    while True:
        print(f"\n{'=' * 60}")
        print(f"  Browsing: {cwd}")
        print(f"{'=' * 60}")

        entries = client.browse_file_list(file_list_id, cwd)

        if not entries:
            print("  (empty directory)")
        else:
            dirs = [e for e in entries if e.isDirectory]
            files = [e for e in entries if not e.isDirectory]

            # Show directories first
            for i, d in enumerate(dirs):
                print(f"  [{i + 1:3d}] DIR   {d.name}/  ({format_size(d.size)})")

            # Then files
            for i, f in enumerate(files, len(dirs) + 1):
                print(f"  [{i:3d}] FILE  {f.name}  ({format_size(f.size)})")
                if f.tth:
                    print(f"        TTH: {f.tth}")

        print(f"\n  Total: {len(dirs)} dirs, {len(files)} files")
        print()
        print("Commands:")
        print("  <number>     — Enter directory or select file")
        print("  ..           — Go up one level")
        print("  /            — Go to root")
        print("  dl <number>  — Download a file")
        print("  dldir <num>  — Download entire directory")
        print("  q            — Quit browser")
        print()

        try:
            cmd = input(f"{cwd}> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd == "q":
            break
        elif cmd == "..":
            if cwd != "/":
                cwd = "/".join(cwd.rstrip("/").split("/")[:-1]) or "/"
        elif cmd == "/":
            cwd = "/"
        elif cmd.startswith("dl "):
            try:
                idx = int(cmd[3:]) - 1
                all_entries = dirs + files
                if 0 <= idx < len(all_entries):
                    entry = all_entries[idx]
                    if entry.isDirectory:
                        print("Use 'dldir' for directories")
                    else:
                        path = f"{cwd.rstrip('/')}/{entry.name}"
                        ok = client.download_from_list(file_list_id, path)
                        print("Queued for download" if ok else "Failed to queue")
                else:
                    print(f"Invalid index: {idx + 1}")
            except ValueError:
                print("Usage: dl <number>")
        elif cmd.startswith("dldir "):
            try:
                idx = int(cmd[6:]) - 1
                if 0 <= idx < len(dirs):
                    d = dirs[idx]
                    path = f"{cwd.rstrip('/')}/{d.name}"
                    ok = client.download_dir_from_list(file_list_id, path)
                    print("Directory queued" if ok else "Failed to queue")
                else:
                    print(f"Invalid index: {idx + 1}")
            except ValueError:
                print("Usage: dldir <number>")
        else:
            try:
                idx = int(cmd) - 1
                all_entries = dirs + files
                if 0 <= idx < len(all_entries):
                    entry = all_entries[idx]
                    if entry.isDirectory:
                        if cwd == "/":
                            cwd = f"/{entry.name}"
                        else:
                            cwd = f"{cwd.rstrip('/')}/{entry.name}"
                    else:
                        print(f"  File: {entry.name}")
                        print(f"  Size: {format_size(entry.size)}")
                        if entry.tth:
                            print(f"  TTH:  {entry.tth}")
                else:
                    print(f"Invalid index: {idx + 1}")
            except ValueError:
                print(f"Unknown command: {cmd}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Browse a user's file list")
    parser.add_argument("hub_url", help="Hub address")
    parser.add_argument("nick", help="User nick whose file list to request")
    parser.add_argument("--config-dir", default="")
    parser.add_argument("--match-queue", action="store_true",
                        help="Auto-match file list against download queue")
    parser.add_argument("--local", metavar="FILE_LIST_ID",
                        help="Open a locally cached file list instead of requesting")
    args = parser.parse_args()

    client = DCClient(args.config_dir)
    if not client.initialize():
        print("ERROR: Failed to initialize DC core", file=sys.stderr)
        sys.exit(1)

    connected = {"ready": False}

    @client.on("hub_connected")
    def on_connected(url, name):
        print(f"[+] Connected to {name}")
        connected["ready"] = True

    @client.on("hub_disconnected")
    def on_disconnected(url, reason):
        print(f"[-] Disconnected: {reason}")

    @client.on("queue_item_added")
    def on_queued(target, size, tth):
        print(f"[Q+] Queued: {target}")

    @client.on("download_complete")
    def on_dl_done(target, nick, size, speed):
        print(f"[OK] Downloaded: {target}")

    if args.local:
        # Open a locally cached file list directly
        file_list_id = args.local
        if not client.open_file_list(file_list_id):
            print(f"ERROR: Could not open file list: {file_list_id}", file=sys.stderr)
            client.shutdown()
            sys.exit(1)

        print(f"Opened local file list: {file_list_id}")
        browse_interactive(client, file_list_id)
        client.close_file_list(file_list_id)

    else:
        # Connect to hub and request file list
        print(f"Connecting to {args.hub_url}...")
        client.connect(args.hub_url)

        for _ in range(30):
            if connected["ready"]:
                break
            time.sleep(1)
        else:
            print("ERROR: Connection timed out", file=sys.stderr)
            client.shutdown()
            sys.exit(1)

        time.sleep(2)  # Let user list populate

        print(f"Requesting file list from {args.nick}...")
        ok = client.request_file_list(args.hub_url, args.nick, args.match_queue)
        if not ok:
            print(f"ERROR: Could not request file list for {args.nick}")
            print("  Make sure the user is online and the nick is correct.")

            # Show available users as hint
            users = client.get_users(args.hub_url)
            if users:
                print(f"\n  Online users ({len(users)}):")
                for u in users[:20]:
                    print(f"    {u.nick}")
                if len(users) > 20:
                    print(f"    ... and {len(users) - 20} more")
            client.shutdown()
            sys.exit(1)

        print("File list requested. Waiting for download...")
        time.sleep(10)

        # Check if we have it locally now
        lists = client.list_local_file_lists()
        matching = [f for f in lists if args.nick.lower() in f.lower()]

        if matching:
            file_list_id = matching[0]
            print(f"Got file list: {file_list_id}")

            if client.open_file_list(file_list_id):
                browse_interactive(client, file_list_id)
                client.close_file_list(file_list_id)
            else:
                print("ERROR: Failed to parse file list")
        else:
            print("File list not yet available. Try again later.")
            if lists:
                print(f"  Available lists: {lists[:10]}")

    client.shutdown()
    print("[*] Done.")


if __name__ == "__main__":
    main()
