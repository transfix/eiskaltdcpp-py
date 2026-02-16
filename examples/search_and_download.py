#!/usr/bin/env python3
"""
Example: Search for files on a hub and download them.

Demonstrates:
  - Connecting to a hub
  - Searching for files by name
  - Filtering search results
  - Adding files to the download queue
  - Adding magnet links
  - Monitoring queue events

Usage:
    python search_and_download.py dchub://hub.example.com:411 "search query"

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and download files on DC")
    parser.add_argument("hub_url", help="Hub address, e.g. dchub://example.com:411")
    parser.add_argument("query", help="Search query string")
    parser.add_argument("--download-dir", default="/tmp/dc-downloads",
                        help="Directory to save downloads (default: /tmp/dc-downloads)")
    parser.add_argument("--config-dir", default="",
                        help="Config directory (default: ~/.eiskaltdcpp-py/)")
    parser.add_argument("--file-type", type=int, default=0, choices=range(9),
                        help="0=any, 1=audio, 2=compressed, 3=document, "
                             "4=executable, 5=picture, 6=video, 7=folder, 8=TTH")
    parser.add_argument("--max-results", type=int, default=20,
                        help="Maximum number of results to display (default: 20)")
    parser.add_argument("--wait", type=int, default=10,
                        help="Seconds to wait for search results (default: 10)")
    parser.add_argument("--auto-download", action="store_true",
                        help="Automatically download the first result")
    args = parser.parse_args()

    client = DCClient(args.config_dir)
    if not client.initialize():
        print("ERROR: Failed to initialize DC core", file=sys.stderr)
        sys.exit(1)

    connected_event = {"ready": False}

    # ─── Event handlers ───

    @client.on("hub_connected")
    def on_connected(hub_url: str, hub_name: str) -> None:
        print(f"[+] Connected to {hub_name}")
        connected_event["ready"] = True

    @client.on("hub_disconnected")
    def on_disconnected(hub_url: str, reason: str) -> None:
        print(f"[-] Disconnected: {reason}")

    result_count = {"n": 0}

    @client.on("search_result")
    def on_result(result) -> None:
        result_count["n"] += 1
        kind = "DIR" if result.isDirectory else "FILE"
        print(f"  [{result_count['n']:3d}] {kind}  {result.fileName}  "
              f"{format_size(result.fileSize)}  "
              f"slots:{result.freeSlots}/{result.totalSlots}  "
              f"from:{result.nick}")

    @client.on("queue_item_added")
    def on_queued(item) -> None:
        print(f"[Q+] Queued: {item.target} ({format_size(item.size)})")

    @client.on("queue_item_finished")
    def on_finished(item) -> None:
        print(f"[OK] Download complete: {item.target}")

    @client.on("download_starting")
    def on_dl_start(transfer) -> None:
        print(f"[DL] Starting: {transfer.target} from {transfer.nick}")

    @client.on("download_complete")
    def on_dl_done(transfer) -> None:
        print(f"[DL] Complete: {transfer.target}")

    @client.on("download_failed")
    def on_dl_fail(transfer, reason: str) -> None:
        print(f"[!!] Failed: {transfer.target} — {reason}")

    # ─── Connect and wait ───

    print(f"Connecting to {args.hub_url}...")
    client.connect(args.hub_url)

    # Wait for connection
    for _ in range(30):
        if connected_event["ready"]:
            break
        time.sleep(1)
    else:
        print("ERROR: Timed out waiting for hub connection", file=sys.stderr)
        client.shutdown()
        sys.exit(1)

    # Give the user list a moment to populate
    time.sleep(2)

    # ─── Search ───

    print(f"\nSearching for: '{args.query}' (type={args.file_type})...")
    client.clear_search_results()
    ok = client.search(args.query, file_type=args.file_type)
    if not ok:
        print("ERROR: Search request failed", file=sys.stderr)
        client.shutdown()
        sys.exit(1)

    print(f"Waiting {args.wait}s for results...\n")
    time.sleep(args.wait)

    # ─── Display results ───

    results = client.get_search_results()
    print(f"\n{'=' * 60}")
    print(f"Got {len(results)} search results for '{args.query}'")
    print(f"{'=' * 60}\n")

    if not results:
        print("No results found.")
        client.shutdown()
        return

    # Sort by free slots descending (prefer sources with available slots)
    results.sort(key=lambda r: r.freeSlots, reverse=True)

    displayed = results[:args.max_results]
    for i, r in enumerate(displayed, 1):
        kind = "DIR " if r.isDirectory else "FILE"
        print(f"  {i:3d}. [{kind}] {r.fileName}")
        print(f"       Size: {format_size(r.fileSize)}  "
              f"Slots: {r.freeSlots}/{r.totalSlots}  "
              f"From: {r.nick}")
        print(f"       TTH:  {r.tth}")
        print()

    if len(results) > args.max_results:
        print(f"  ... {len(results) - args.max_results} more results not shown\n")

    # ─── Download ───

    if args.auto_download:
        r = displayed[0]
        if not r.isDirectory:
            print(f"Auto-downloading: {r.fileName}...")
            ok = client.download(args.download_dir, r.fileName, r.fileSize, r.tth)
            if ok:
                print(f"Added to queue. Downloading to {args.download_dir}/")
                # Wait a bit for transfer to start
                time.sleep(5)
            else:
                print("Failed to add to queue")
        else:
            print(f"First result is a directory, skipping auto-download")
    else:
        # Interactive selection
        print("Enter result number to download (or 'q' to quit, 'm' for magnet):")
        try:
            choice = input("> ").strip()
        except EOFError:
            choice = "q"

        if choice == "q":
            pass
        elif choice == "m":
            magnet = input("Paste magnet link: ").strip()
            if magnet:
                ok = client.download_magnet(magnet, args.download_dir)
                print("Added to queue" if ok else "Failed to parse magnet")
                time.sleep(5)
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(displayed):
                    r = displayed[idx]
                    ok = client.download(
                        args.download_dir, r.fileName, r.fileSize, r.tth
                    )
                    if ok:
                        print(f"Added to queue: {r.fileName}")
                        print("Waiting for transfer... (Ctrl+C to quit)")

                        # Wait for download, showing progress
                        for _ in range(120):  # Up to 2 minutes
                            stats = client.transfer_stats
                            if stats.downloadCount > 0:
                                print(f"  DL speed: {format_size(int(stats.downloadSpeed))}/s  "
                                      f"  Active: {stats.downloadCount}")
                            time.sleep(2)
                    else:
                        print("Failed to add to queue")
                else:
                    print(f"Invalid selection: {choice}")
            except ValueError:
                print(f"Invalid input: {choice}")

    client.shutdown()
    print("[*] Done.")


if __name__ == "__main__":
    main()
