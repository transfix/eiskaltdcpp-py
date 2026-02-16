#!/usr/bin/env python3
"""
Example: Monitor download progress with periodic status updates.

Demonstrates:
  - Tracking active downloads in real-time
  - Using transfer callbacks for start/complete/fail events
  - Polling transfer statistics for aggregate speed info
  - Queue event monitoring
  - Displaying a live progress dashboard

Usage:
    python download_progress.py dchub://hub.example.com:411

    Once connected, use the search_and_download.py example (or another DC
    client) to queue some downloads, and watch the progress here.

Press Ctrl+C to quit.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from eiskaltdcpp import DCClient


def format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 0:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def format_speed(bytes_per_sec: int) -> str:
    """Format transfer speed."""
    return f"{format_size(bytes_per_sec)}/s"


def format_eta(remaining_bytes: int, speed: int) -> str:
    """Estimate time remaining."""
    if speed <= 0 or remaining_bytes <= 0:
        return "∞"
    secs = remaining_bytes / speed
    if secs < 60:
        return f"{secs:.0f}s"
    elif secs < 3600:
        return f"{secs / 60:.0f}m {secs % 60:.0f}s"
    else:
        return f"{secs / 3600:.0f}h {(secs % 3600) / 60:.0f}m"


@dataclass
class ActiveTransfer:
    """Track state of an active transfer."""
    target: str
    nick: str
    hub_url: str
    size: int
    transferred: int = 0
    speed: int = 0
    is_download: bool = True
    started_at: float = field(default_factory=time.time)
    completed: bool = False
    failed: bool = False
    fail_reason: str = ""


class ProgressTracker:
    """Thread-safe tracker for active and completed transfers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: OrderedDict[str, ActiveTransfer] = OrderedDict()
        self._completed: list[ActiveTransfer] = []
        self._failed: list[ActiveTransfer] = []
        self._queued: int = 0
        self._finished: int = 0

    def on_download_starting(self, transfer) -> None:
        with self._lock:
            t = ActiveTransfer(
                target=transfer.target,
                nick=transfer.nick,
                hub_url=transfer.hubUrl,
                size=transfer.size,
                transferred=transfer.transferred,
                speed=transfer.speed,
                is_download=True,
            )
            self._active[transfer.target] = t
        self._print_event(f"[DL START] {os.path.basename(transfer.target)} "
                          f"from {transfer.nick}")

    def on_download_complete(self, transfer) -> None:
        with self._lock:
            t = self._active.pop(transfer.target, None)
            if t:
                t.completed = True
                self._completed.append(t)
            self._finished += 1
        self._print_event(f"[DL DONE]  {os.path.basename(transfer.target)} "
                          f"({format_size(transfer.size)})")

    def on_download_failed(self, transfer, reason: str) -> None:
        with self._lock:
            t = self._active.pop(transfer.target, None)
            if t:
                t.failed = True
                t.fail_reason = reason
                self._failed.append(t)
        self._print_event(f"[DL FAIL]  {os.path.basename(transfer.target)}: "
                          f"{reason}")

    def on_upload_starting(self, transfer) -> None:
        self._print_event(f"[UL START] {os.path.basename(transfer.target)} "
                          f"to {transfer.nick}")

    def on_upload_complete(self, transfer) -> None:
        self._print_event(f"[UL DONE]  {os.path.basename(transfer.target)}")

    def on_queue_added(self, item) -> None:
        with self._lock:
            self._queued += 1
        self._print_event(f"[QUEUED]   {os.path.basename(item.target)} "
                          f"({format_size(item.size)})")

    def on_queue_finished(self, item) -> None:
        self._print_event(f"[Q DONE]   {os.path.basename(item.target)}")

    def on_queue_removed(self, target: str) -> None:
        with self._lock:
            self._queued = max(0, self._queued - 1)

    def print_dashboard(self, stats) -> None:
        """Print a snapshot of current transfer state."""
        with self._lock:
            active = list(self._active.values())
            completed_count = len(self._completed)
            failed_count = len(self._failed)
            queued = self._queued

        # Clear screen (simple approach)
        print(f"\n{'─' * 70}")
        print(f"  TRANSFER DASHBOARD"
              f"  │  DL: {format_speed(int(stats.downloadSpeed))}"
              f"  UL: {format_speed(int(stats.uploadSpeed))}"
              f"  │  Active: {stats.downloadCount} DL / {stats.uploadCount} UL")
        print(f"  Queued: {queued}  │  Completed: {completed_count}"
              f"  │  Failed: {failed_count}"
              f"  │  Total DL: {format_size(stats.totalDownloaded)}"
              f"  UL: {format_size(stats.totalUploaded)}")
        print(f"{'─' * 70}")

        if active:
            for t in active:
                name = os.path.basename(t.target)
                if len(name) > 35:
                    name = name[:32] + "..."

                if t.size > 0:
                    pct = (t.transferred / t.size) * 100
                    bar_len = 20
                    filled = int(bar_len * t.transferred / t.size)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    remaining = t.size - t.transferred
                    eta = format_eta(remaining, t.speed)
                    print(f"  {name:35s}  [{bar}] {pct:5.1f}%  "
                          f"{format_speed(t.speed)}  ETA:{eta}")
                else:
                    print(f"  {name:35s}  [connecting...]  from {t.nick}")
        else:
            print("  No active transfers")

        print(f"{'─' * 70}")

    @staticmethod
    def _print_event(msg: str) -> None:
        """Print a timestamped event message."""
        ts = time.strftime("%H:%M:%S")
        print(f"  {ts}  {msg}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor DC download progress in real-time"
    )
    parser.add_argument("hub_url", help="Hub address")
    parser.add_argument("--config-dir", default="")
    parser.add_argument("--refresh", type=float, default=2.0,
                        help="Dashboard refresh interval in seconds (default: 2)")
    args = parser.parse_args()

    client = DCClient(args.config_dir)
    if not client.initialize():
        print("ERROR: Failed to initialize DC core", file=sys.stderr)
        sys.exit(1)

    tracker = ProgressTracker()

    # ─── Wire up events ───

    @client.on("hub_connected")
    def on_connected(url, name):
        print(f"\n[+] Connected to {name} ({url})\n")

    @client.on("hub_disconnected")
    def on_disconnected(url, reason):
        print(f"\n[-] Disconnected from {url}: {reason}\n")

    client.on("download_starting", tracker.on_download_starting)
    client.on("download_complete", tracker.on_download_complete)
    client.on("download_failed", tracker.on_download_failed)
    client.on("upload_starting", tracker.on_upload_starting)
    client.on("upload_complete", tracker.on_upload_complete)
    client.on("queue_item_added", tracker.on_queue_added)
    client.on("queue_item_finished", tracker.on_queue_finished)
    client.on("queue_item_removed", tracker.on_queue_removed)

    # ─── Connect ───

    print(f"Connecting to {args.hub_url}...")
    client.connect(args.hub_url)

    # ─── Main loop ───

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False
        print("\n[*] Shutting down...")

    signal.signal(signal.SIGINT, signal_handler)

    print("\nMonitoring transfers. Queue downloads to see progress.")
    print("Press Ctrl+C to quit.\n")

    try:
        while running:
            stats = client.transfer_stats
            tracker.print_dashboard(stats)
            time.sleep(args.refresh)
    finally:
        client.shutdown()
        print("[*] Done.")


if __name__ == "__main__":
    main()
