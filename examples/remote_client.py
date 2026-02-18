#!/usr/bin/env python3
"""
remote_client.py — Control a DC client over the REST API.

Demonstrates using ``RemoteDCClient`` to control an eiskaltdcpp-py API
server from a separate process or machine.  The remote client mirrors
the ``AsyncDCClient`` interface but communicates over HTTP + WebSocket.

Prerequisites:
    pip install eiskaltdcpp-py[api]

    # Start the API server (in another terminal or on a remote machine):
    python -m eiskaltdcpp.api --admin-user admin --admin-pass s3cret

Usage:
    python examples/remote_client.py --url http://localhost:8080
    python examples/remote_client.py --url http://dc-server:9000 \\
        --user admin --pass s3cret --hub dchub://hub.example.com:411
    python examples/remote_client.py --help
"""
from __future__ import annotations

import argparse
import asyncio
import sys


async def demo_status(client):
    """Show server status and connected hubs."""
    status = await client.get_status()
    print(f"Server version : {status.get('version', '?')}")
    print(f"DC client      : {'connected' if status.get('initialized') else 'not configured'}")
    print(f"Uptime         : {status.get('uptime_seconds', 0):.0f}s")
    print()

    hubs = await client.list_hubs_async()
    if hubs:
        print(f"Connected hubs ({len(hubs)}):")
        for h in hubs:
            print(f"  {h.url}  —  {h.name}  ({h.user_count} users)")
    else:
        print("No hubs connected.")
    print()


async def demo_connect(client, hub_url: str):
    """Connect to a hub and list users."""
    print(f"Connecting to {hub_url} ...")
    await client.connect(hub_url)

    # Give the hub a moment to populate the user list
    await asyncio.sleep(3)

    users = await client.get_users_async(hub_url)
    print(f"Users on {hub_url} ({len(users)}):")
    for u in users[:20]:  # first 20
        share_mb = u.share_size / (1024 * 1024)
        print(f"  {u.nick:30s}  {share_mb:>10.1f} MB")
    if len(users) > 20:
        print(f"  ... and {len(users) - 20} more")
    print()


async def demo_search(client, query: str):
    """Run a search and display results."""
    print(f"Searching for '{query}' ...")
    await client.search_async(query)

    # Wait for results to trickle in
    await asyncio.sleep(5)

    results = await client.get_search_results_async()
    print(f"Search results ({len(results)}):")
    for r in results[:15]:
        size_mb = r.size / (1024 * 1024)
        print(f"  {r.file:50s}  {size_mb:>8.1f} MB  from {r.nick}")
    if len(results) > 15:
        print(f"  ... and {len(results) - 15} more")
    print()


async def demo_shares(client):
    """List shared directories."""
    shares = await client.list_shares_async()
    if shares:
        print(f"Shared directories ({len(shares)}):")
        for s in shares:
            size_mb = s.size / (1024 * 1024)
            print(f"  {s.virtual_name:30s}  {s.real_path}  ({size_mb:.1f} MB)")
    else:
        print("No directories shared.")
    print()


async def demo_queue(client):
    """List the download queue."""
    queue = await client.list_queue_async()
    if queue:
        print(f"Download queue ({len(queue)}):")
        for q in queue:
            pct = (q.downloaded / q.size * 100) if q.size > 0 else 0
            print(f"  {q.target:50s}  {pct:5.1f}%  ({q.size} bytes)")
    else:
        print("Download queue is empty.")
    print()


async def demo_events(client, duration: float = 10.0):
    """Listen to real-time events for a few seconds."""
    print(f"Listening for events ({duration}s) ...")
    stream = client.events("events,chat,hubs")
    try:
        async with asyncio.timeout(duration):
            async for event, data in stream:
                print(f"  [{event}] {data}")
    except (asyncio.TimeoutError, TimeoutError):
        pass
    finally:
        await stream.close()
    print()


async def demo_user_management(client):
    """Create, list, and delete an API user."""
    print("API user management demo:")

    # Create a readonly user
    try:
        user = await client.create_user("demo_reader", "readpass123", "readonly")
        print(f"  Created user: {user}")
    except Exception as exc:
        print(f"  Create user: {exc}")

    # List users
    users = await client.list_users()
    print(f"  Users ({len(users)}): {[u.get('username') for u in users]}")

    # Delete the demo user
    try:
        await client.delete_user("demo_reader")
        print("  Deleted demo_reader")
    except Exception as exc:
        print(f"  Delete user: {exc}")
    print()


async def main(args: argparse.Namespace) -> None:
    from eiskaltdcpp.api.client import RemoteDCClient

    async with RemoteDCClient(
        args.url,
        username=args.user,
        password=getattr(args, "pass"),
    ) as client:
        print(f"Authenticated to {args.url}\n")

        # Always show status
        await demo_status(client)

        # Connect to a hub if requested
        if args.hub:
            await demo_connect(client, args.hub)

        # Search if requested
        if args.search:
            await demo_search(client, args.search)

        # Show shares and queue
        await demo_shares(client)
        await demo_queue(client)

        # User management demo (admin only)
        if args.users:
            await demo_user_management(client)

        # Listen for events if requested
        if args.listen:
            await demo_events(client, args.listen)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="RemoteDCClient demo — control a DC client via REST API",
    )
    parser.add_argument(
        "--url", default="http://localhost:8080",
        help="API server URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--user", default="admin",
        help="API username (default: admin)",
    )
    parser.add_argument(
        "--pass", default="changeme", dest="pass",
        help="API password (default: changeme)",
    )
    parser.add_argument(
        "--hub",
        help="Hub URL to connect to (e.g. dchub://hub.example.com:411)",
    )
    parser.add_argument(
        "--search",
        help="Search query to run after connecting",
    )
    parser.add_argument(
        "--listen", type=float, default=0,
        help="Listen for real-time events for N seconds",
    )
    parser.add_argument(
        "--users", action="store_true",
        help="Run user management demo (create/list/delete)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
