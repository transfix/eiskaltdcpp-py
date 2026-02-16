#!/usr/bin/env python3
"""
Example: Multi-hub bot that connects to multiple hubs simultaneously.

Demonstrates:
  - Connecting to multiple hubs at once
  - Per-hub event handling
  - Auto-reconnect on disconnect
  - Command handling (bot responds to chat commands)
  - User tracking across hubs
  - Transfer statistics aggregation

Usage:
    python multi_hub_bot.py dchub://hub1.example.com dchub://hub2.example.com

Press Ctrl+C to quit.
"""
from __future__ import annotations

import argparse
import re
import signal
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime

from eiskaltdcpp import DCClient


def format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


class HubBot:
    """A simple bot that connects to multiple hubs and responds to commands."""

    # Chat commands the bot responds to
    COMMANDS = {
        "!help":   "Show available commands",
        "!stats":  "Show transfer statistics",
        "!hubs":   "Show connected hubs",
        "!uptime": "Show bot uptime",
        "!users":  "Show user count on this hub",
        "!share":  "Show share statistics",
    }

    def __init__(self, config_dir: str = "") -> None:
        self.client = DCClient(config_dir)
        self._start_time = time.time()
        self._lock = threading.Lock()
        self._user_counts: dict[str, int] = {}
        self._reconnect_delays: dict[str, int] = defaultdict(lambda: 5)
        self._should_reconnect: dict[str, bool] = {}

    def start(self, hub_urls: list[str], encodings: dict[str, str] | None = None) -> None:
        """Initialize and connect to all hubs."""
        if not self.client.initialize():
            print("ERROR: Failed to initialize", file=sys.stderr)
            sys.exit(1)

        encodings = encodings or {}

        # Register event handlers
        self._register_handlers()

        # Connect to all hubs
        for url in hub_urls:
            self._should_reconnect[url] = True
            encoding = encodings.get(url, "")
            print(f"[*] Connecting to {url}...")
            self.client.connect(url, encoding)

    def stop(self) -> None:
        """Disconnect and shut down."""
        # Disable auto-reconnect
        for url in self._should_reconnect:
            self._should_reconnect[url] = False
        self.client.shutdown()

    def _register_handlers(self) -> None:
        """Register all event handlers on the client."""

        @self.client.on("hub_connected")
        def on_connected(hub_url: str, hub_name: str) -> None:
            print(f"[+] Connected to {hub_name} ({hub_url})")
            with self._lock:
                self._reconnect_delays[hub_url] = 5  # Reset delay

        @self.client.on("hub_disconnected")
        def on_disconnected(hub_url: str, reason: str) -> None:
            print(f"[-] Disconnected from {hub_url}: {reason}")
            # Auto-reconnect with exponential backoff
            if self._should_reconnect.get(hub_url, False):
                delay = self._reconnect_delays[hub_url]
                print(f"[*] Reconnecting to {hub_url} in {delay}s...")
                threading.Timer(delay, self._reconnect, args=[hub_url]).start()
                with self._lock:
                    self._reconnect_delays[hub_url] = min(delay * 2, 300)

        @self.client.on("hub_redirect")
        def on_redirect(hub_url: str, new_url: str) -> None:
            print(f"[>] Redirect: {hub_url} → {new_url}")
            self._should_reconnect[hub_url] = False
            self._should_reconnect[new_url] = True
            self.client.disconnect(hub_url)
            self.client.connect(new_url)

        @self.client.on("chat_message")
        def on_chat(hub_url: str, nick: str, message: str,
                    third_person: bool = False) -> None:
            ts = time.strftime("%H:%M:%S")
            hub_short = hub_url.split("://")[-1].split(":")[0]
            prefix = "* " if third_person else ""
            print(f"  {ts} [{hub_short}] <{nick}> {prefix}{message}")

            # Check for bot commands
            msg = message.strip()
            if msg.startswith("!"):
                self._handle_command(hub_url, nick, msg)

        @self.client.on("private_message")
        def on_pm(hub_url: str, from_nick: str, to_nick: str,
                  message: str) -> None:
            ts = time.strftime("%H:%M:%S")
            print(f"  {ts} [PM from {from_nick}] {message}")

            # Respond to PM commands too
            msg = message.strip()
            if msg.startswith("!"):
                self._handle_command(hub_url, from_nick, msg, private=True)

        @self.client.on("user_connected")
        def on_user_join(hub_url: str, nick: str) -> None:
            with self._lock:
                self._user_counts[hub_url] = self._user_counts.get(hub_url, 0) + 1

        @self.client.on("user_disconnected")
        def on_user_part(hub_url: str, nick: str) -> None:
            with self._lock:
                self._user_counts[hub_url] = max(
                    0, self._user_counts.get(hub_url, 1) - 1
                )

    def _reconnect(self, hub_url: str) -> None:
        """Attempt to reconnect to a hub."""
        if self._should_reconnect.get(hub_url, False):
            print(f"[*] Reconnecting to {hub_url}...")
            self.client.connect(hub_url)

    def _handle_command(
        self,
        hub_url: str,
        nick: str,
        command: str,
        private: bool = False,
    ) -> None:
        """Handle a bot command from chat."""
        cmd = command.split()[0].lower()
        response = ""

        if cmd == "!help":
            lines = ["Available commands:"]
            for c, desc in self.COMMANDS.items():
                lines.append(f"  {c} — {desc}")
            response = "\n".join(lines)

        elif cmd == "!stats":
            stats = self.client.transfer_stats
            response = (
                f"Transfer stats: "
                f"DL {format_size(int(stats.downloadSpeed))}/s "
                f"({stats.downloadCount} active), "
                f"UL {format_size(int(stats.uploadSpeed))}/s "
                f"({stats.uploadCount} active), "
                f"Total DL {format_size(stats.totalDownloaded)}, "
                f"UL {format_size(stats.totalUploaded)}"
            )

        elif cmd == "!hubs":
            hubs = self.client.list_hubs()
            lines = [f"Connected to {len(hubs)} hubs:"]
            for h in hubs:
                status = "●" if h.connected else "○"
                lines.append(
                    f"  {status} {h.name} ({h.url}) — "
                    f"{h.userCount} users"
                )
            response = "\n".join(lines)

        elif cmd == "!uptime":
            elapsed = time.time() - self._start_time
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            response = f"Uptime: {hours}h {minutes}m"

        elif cmd == "!users":
            users = self.client.get_users(hub_url)
            response = f"Users online: {len(users)}"

        elif cmd == "!share":
            response = (
                f"Sharing {self.client.shared_files} files "
                f"({format_size(self.client.share_size)})"
            )

        if response:
            if private:
                self.client.send_pm(hub_url, nick, response)
            else:
                self.client.send_message(hub_url, response)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-hub DC bot with auto-reconnect"
    )
    parser.add_argument(
        "hub_urls", nargs="+",
        help="One or more hub addresses to connect to"
    )
    parser.add_argument("--config-dir", default="")
    args = parser.parse_args()

    bot = HubBot(args.config_dir)
    bot.start(args.hub_urls)

    # Wait for Ctrl+C
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False
        print("\n[*] Shutting down bot...")

    signal.signal(signal.SIGINT, signal_handler)

    print("\nBot running. Press Ctrl+C to quit.\n")

    try:
        while running:
            time.sleep(1)
    finally:
        bot.stop()
        print("[*] Bot stopped.")


if __name__ == "__main__":
    main()
