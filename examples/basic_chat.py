#!/usr/bin/env python3
"""
Example: Connect to a hub, join chat, and send messages.

Demonstrates:
  - Initializing the DC client
  - Connecting to an NMDC hub
  - Receiving public chat messages
  - Sending public messages
  - Sending private messages
  - Handling hub events (connect, disconnect, nick taken, etc.)

Usage:
    python basic_chat.py dchub://your-hub.example.com:411

Press Ctrl+C to quit.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from eiskaltdcpp import DCClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect to a DC hub and chat")
    parser.add_argument("hub_url", help="Hub address, e.g. dchub://example.com:411")
    parser.add_argument("--config-dir", default="", help="Config directory (default: ~/.eiskaltdcpp-py/)")
    parser.add_argument("--encoding", default="", help="Hub encoding, e.g. CP1252 (default: UTF-8)")
    parser.add_argument("--nick", default="", help="Set nick before connecting")
    args = parser.parse_args()

    # Create client
    client = DCClient(args.config_dir)
    if not client.initialize():
        print("ERROR: Failed to initialize DC core", file=sys.stderr)
        sys.exit(1)

    # Optionally set nick
    if args.nick:
        client.set_setting("Nick", args.nick)

    # ─── Register event handlers ───

    @client.on("hub_connecting")
    def on_connecting(hub_url: str) -> None:
        print(f"[*] Connecting to {hub_url}...")

    @client.on("hub_connected")
    def on_connected(hub_url: str, hub_name: str) -> None:
        print(f"[+] Connected to {hub_name} ({hub_url})")
        # Send a greeting after connecting
        # client.send_message(hub_url, "Hello from eiskaltdcpp-py!")

    @client.on("hub_disconnected")
    def on_disconnected(hub_url: str, reason: str) -> None:
        print(f"[-] Disconnected from {hub_url}: {reason}")

    @client.on("hub_redirect")
    def on_redirect(hub_url: str, new_url: str) -> None:
        print(f"[>] Hub {hub_url} redirecting to {new_url}")
        # Automatically follow the redirect
        client.disconnect(hub_url)
        client.connect(new_url, args.encoding)

    @client.on("hub_nick_taken")
    def on_nick_taken(hub_url: str) -> None:
        print(f"[!] Nick already taken on {hub_url}")

    @client.on("hub_full")
    def on_hub_full(hub_url: str) -> None:
        print(f"[!] Hub {hub_url} is full")

    @client.on("hub_get_password")
    def on_password(hub_url: str) -> None:
        print(f"[?] Hub {hub_url} requires a password (set via config)")

    @client.on("chat_message")
    def on_chat(hub_url: str, nick: str, message: str) -> None:
        print(f"<{nick}> {message}")

    @client.on("private_message")
    def on_pm(hub_url: str, nick: str, message: str) -> None:
        print(f"[PM from {nick}] {message}")

    @client.on("status_message")
    def on_status(hub_url: str, message: str) -> None:
        print(f"*** {message}")

    @client.on("user_connected")
    def on_user_join(hub_url: str, user) -> None:
        print(f"  → {user.nick} joined")

    @client.on("user_disconnected")
    def on_user_part(hub_url: str, user) -> None:
        print(f"  ← {user.nick} left")

    # ─── Connect ───

    print(f"Connecting to {args.hub_url}...")
    client.connect(args.hub_url, args.encoding)

    # ─── Interactive loop ───

    print("\nType messages to send to the hub (or commands):")
    print("  /pm <nick> <message>  — Send a private message")
    print("  /users                — List online users")
    print("  /hubs                 — Show connected hubs")
    print("  /quit                 — Disconnect and exit")
    print()

    # Handle Ctrl+C gracefully
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False
        print("\n[*] Shutting down...")

    signal.signal(signal.SIGINT, signal_handler)

    try:
        while running:
            try:
                line = input()
            except EOFError:
                break

            if not line.strip():
                continue

            if line.startswith("/quit"):
                break
            elif line.startswith("/users"):
                users = client.get_users(args.hub_url)
                print(f"--- {len(users)} users online ---")
                for u in users[:50]:  # Show first 50
                    op_flag = " [OP]" if u.isOp else ""
                    share_mb = u.shareSize / (1024 * 1024)
                    print(f"  {u.nick}{op_flag} — {share_mb:.0f} MB shared")
                if len(users) > 50:
                    print(f"  ... and {len(users) - 50} more")
            elif line.startswith("/hubs"):
                hubs = client.list_hubs()
                for h in hubs:
                    status = "connected" if h.connected else "disconnected"
                    print(f"  {h.name} ({h.url}) — {status}, {h.userCount} users")
            elif line.startswith("/pm "):
                parts = line[4:].split(" ", 1)
                if len(parts) == 2:
                    nick, msg = parts
                    client.send_pm(args.hub_url, nick, msg)
                    print(f"[PM to {nick}] {msg}")
                else:
                    print("Usage: /pm <nick> <message>")
            else:
                client.send_message(args.hub_url, line)
    finally:
        client.shutdown()
        print("[*] Bye!")


if __name__ == "__main__":
    main()
