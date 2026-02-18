#!/usr/bin/env python3
"""
Subprocess DC client worker — runs one AsyncDCClient in an isolated process.

Communicates via JSON-lines over stdin/stdout:
  - Parent sends commands as JSON objects: {"cmd": "...", "args": {...}, "id": N}
  - Worker replies with:  {"id": N, "ok": true, "result": ...}
                      or: {"id": N, "ok": false, "error": "..."}
  - Unsolicited events:   {"event": "...", "args": [...]}

The worker keeps its own asyncio event loop and DC client.  Because it
lives in a separate process, it gets its own set of dcpp singletons,
side-stepping the in-process singleton limitation entirely.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

# Locate the SWIG build dir when running from the repo checkout
BUILD_DIR = Path(__file__).parent.parent / "build" / "python"
if BUILD_DIR.exists():
    sys.path.insert(0, str(BUILD_DIR))

from eiskaltdcpp import AsyncDCClient

logger = logging.getLogger("dc_worker")


class DCWorker:
    """JSON-lines RPC wrapper around AsyncDCClient."""

    def __init__(self) -> None:
        self.client: AsyncDCClient | None = None
        self.cfg_dir: Path | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._event_task: asyncio.Task | None = None
        self._running = True
        self._write_lock = threading.Lock()  # guards stdout writes

    # -- I/O helpers -------------------------------------------------------

    def _write(self, obj: dict) -> None:
        """Write a JSON line to stdout (thread-safe)."""
        line = json.dumps(obj, default=str) + "\n"
        with self._write_lock:
            sys.stdout.write(line)
            sys.stdout.flush()

    def _reply(self, msg_id: int, result: Any = None) -> None:
        self._write({"id": msg_id, "ok": True, "result": result})

    def _reply_err(self, msg_id: int, error: str) -> None:
        self._write({"id": msg_id, "ok": False, "error": error})

    def _emit_event(self, name: str, args: tuple) -> None:
        self._write({"event": name, "args": list(args)})

    # -- Command dispatch --------------------------------------------------

    async def handle(self, msg: dict) -> None:
        """Dispatch a single command message."""
        msg_id = msg.get("id", 0)
        cmd = msg.get("cmd", "")
        args = msg.get("args", {})

        try:
            result = await self._dispatch(cmd, args)
            self._reply(msg_id, result)
        except Exception as e:
            self._reply_err(msg_id, f"{type(e).__name__}: {e}")

    async def _dispatch(self, cmd: str, args: dict) -> Any:
        if cmd == "init":
            return await self._cmd_init(args)
        elif cmd == "connect":
            return await self._cmd_connect(args)
        elif cmd == "disconnect":
            return await self._cmd_disconnect(args)
        elif cmd == "set_setting":
            return self._cmd_set_setting(args)
        elif cmd == "get_setting":
            return self._cmd_get_setting(args)
        elif cmd == "is_connected":
            return self._cmd_is_connected(args)
        elif cmd == "list_hubs":
            return self._cmd_list_hubs()
        elif cmd == "get_users":
            return self._cmd_get_users(args)
        elif cmd == "send_pm":
            return self._cmd_send_pm(args)
        elif cmd == "wait_pm":
            return await self._cmd_wait_pm(args)
        elif cmd == "send_message":
            return self._cmd_send_message(args)
        elif cmd == "search":
            return await self._cmd_search(args)
        elif cmd == "add_share":
            return self._cmd_add_share(args)
        elif cmd == "refresh_share":
            return self._cmd_refresh_share()
        elif cmd == "request_file_list":
            return self._cmd_request_file_list(args)
        elif cmd == "request_and_browse_file_list":
            return await self._cmd_request_and_browse_file_list(args)
        elif cmd == "list_local_file_lists":
            return self._cmd_list_local_file_lists()
        elif cmd == "open_file_list":
            return self._cmd_open_file_list(args)
        elif cmd == "browse_file_list":
            return self._cmd_browse_file_list(args)
        elif cmd == "download_from_list":
            return self._cmd_download_from_list(args)
        elif cmd == "download_and_wait":
            return await self._cmd_download_and_wait(args)
        elif cmd == "list_queue":
            return self._cmd_list_queue()
        elif cmd == "clear_queue":
            return self._cmd_clear_queue()
        elif cmd == "close_file_list":
            return self._cmd_close_file_list(args)
        elif cmd == "close_all_file_lists":
            return self._cmd_close_all_file_lists()
        elif cmd == "get_share_size":
            return self._cmd_get_share_size()
        elif cmd == "start_networking":
            return self._cmd_start_networking()
        elif cmd == "shutdown":
            return await self._cmd_shutdown()
        elif cmd == "ping":
            return "pong"
        else:
            raise ValueError(f"Unknown command: {cmd}")

    # -- Command implementations -------------------------------------------

    async def _cmd_init(self, args: dict) -> bool:
        cfg = args.get("config_dir", "")
        if not cfg:
            self.cfg_dir = Path(tempfile.mkdtemp(prefix="dcpy_worker_"))
            cfg = str(self.cfg_dir)

        self.client = AsyncDCClient(cfg)
        timeout = args.get("timeout", 60)
        ok = await self.client.initialize(timeout=timeout)

        if ok:
            # Wire up event forwarding
            for event_name in [
                "hub_connected", "hub_disconnected", "chat_message",
                "private_message", "user_connected", "user_disconnected",
                "search_result",
                "download_starting", "download_complete", "download_failed",
                "upload_starting", "upload_complete",
                "queue_item_added", "queue_item_finished", "queue_item_removed",
            ]:
                self.client.on(event_name, self._make_forwarder(event_name))

        return ok

    def _make_forwarder(self, name: str):
        """Create a callback that forwards events to the parent."""
        def forwarder(*args):
            self._emit_event(name, args)
        return forwarder

    async def _cmd_connect(self, args: dict) -> None:
        hub = args["hub_url"]
        timeout = args.get("timeout", 45)
        wait = args.get("wait", True)
        await self.client.connect(hub, wait=wait, timeout=timeout)

    async def _cmd_disconnect(self, args: dict) -> None:
        await self.client.disconnect(args["hub_url"])

    def _cmd_set_setting(self, args: dict) -> None:
        self.client.set_setting(args["name"], args["value"])

    def _cmd_get_setting(self, args: dict) -> str:
        return self.client.get_setting(args["name"])

    def _cmd_is_connected(self, args: dict) -> bool:
        return self.client.is_connected(args["hub_url"])

    def _cmd_list_hubs(self) -> list:
        hubs = self.client.list_hubs()
        return [
            {
                "url": h.url,
                "name": h.name,
                "connected": h.connected,
                "userCount": h.userCount,
            }
            for h in hubs
        ]

    def _cmd_get_users(self, args: dict) -> list:
        users = self.client.get_users(args["hub_url"])
        return [{"nick": u.nick} for u in users]

    def _cmd_send_pm(self, args: dict) -> None:
        self.client.send_pm(args["hub_url"], args["nick"], args["message"])

    async def _cmd_wait_pm(self, args: dict) -> dict:
        timeout = args.get("timeout", 20)
        from_nick = args.get("from_nick")
        pm = await self.client.wait_pm(
            from_nick=from_nick, timeout=timeout
        )
        return {
            "hub_url": pm[0],
            "from_nick": pm[1],
            "to_nick": pm[2],
            "message": pm[3],
        }

    def _cmd_send_message(self, args: dict) -> None:
        self.client.send_message(args["hub_url"], args["message"])

    async def _cmd_search(self, args: dict) -> list:
        timeout = args.get("timeout", 30)
        min_results = args.get("min_results", 0)
        results = await self.client.search_and_wait(
            args["query"],
            hub_url=args.get("hub_url", ""),
            timeout=timeout,
            min_results=min_results,
        )
        return results

    def _cmd_add_share(self, args: dict) -> bool:
        return self.client.add_share(args["real_path"], args["virtual_name"])

    def _cmd_refresh_share(self) -> None:
        self.client.refresh_share()

    # -- File list commands ------------------------------------------------

    def _cmd_request_file_list(self, args: dict) -> bool:
        return self.client.request_file_list(
            args["hub_url"], args["nick"],
            match_queue=args.get("match_queue", False),
        )

    async def _cmd_request_and_browse_file_list(self, args: dict) -> dict:
        timeout = args.get("timeout", 60)
        fl_id, entries = await self.client.request_and_browse_file_list(
            args["hub_url"], args["nick"], timeout=timeout,
        )
        return {
            "file_list_id": fl_id,
            "entries": [
                {
                    "name": e.name,
                    "size": e.size,
                    "tth": getattr(e, "tth", ""),
                    "isDirectory": e.isDirectory,
                }
                for e in entries
            ],
        }

    def _cmd_list_local_file_lists(self) -> list:
        return self.client.list_local_file_lists()

    def _cmd_open_file_list(self, args: dict) -> bool:
        return self.client.open_file_list(args["file_list_id"])

    def _cmd_browse_file_list(self, args: dict) -> list:
        entries = self.client.browse_file_list(
            args["file_list_id"],
            directory=args.get("directory", "/"),
        )
        return [
            {
                "name": e.name,
                "size": e.size,
                "tth": getattr(e, "tth", ""),
                "isDirectory": e.isDirectory,
            }
            for e in entries
        ]

    def _cmd_download_from_list(self, args: dict) -> bool:
        return self.client.download_from_list(
            args["file_list_id"],
            args["file_path"],
            download_to=args.get("download_to", ""),
        )

    async def _cmd_download_and_wait(self, args: dict) -> dict:
        timeout = args.get("timeout", 120)
        ok, err = await self.client.download_and_wait(
            args["directory"], args["name"],
            args["size"], args["tth"],
            timeout=timeout,
        )
        return {"ok": ok, "error": err}

    def _cmd_list_queue(self) -> list:
        items = self.client.list_queue()
        return [
            {
                "target": q.target,
                "filename": q.filename,
                "size": q.size,
                "downloadedBytes": q.downloadedBytes,
                "tth": q.tth,
                "priority": q.priority,
                "sources": q.sources,
                "onlineSources": q.onlineSources,
                "status": q.status,
            }
            for q in items
        ]

    def _cmd_clear_queue(self) -> None:
        self.client.clear_queue()

    def _cmd_close_file_list(self, args: dict) -> None:
        self.client.close_file_list(args["file_list_id"])

    def _cmd_close_all_file_lists(self) -> None:
        self.client.close_all_file_lists()

    def _cmd_get_share_size(self) -> int:
        return self.client.share_size

    # -- Lifecycle ---------------------------------------------------------

    async def _cmd_shutdown(self) -> None:
        if self.client:
            await self.client.shutdown()
            self.client = None
        if self.cfg_dir and self.cfg_dir.exists():
            shutil.rmtree(self.cfg_dir, ignore_errors=True)
        self._running = False

    # -- Main loop ---------------------------------------------------------

    async def run(self) -> None:
        """Read JSON commands from stdin, dispatch, reply on stdout."""
        loop = asyncio.get_running_loop()

        # Read from stdin in a thread to avoid blocking the event loop
        reader = asyncio.Queue()

        def _stdin_reader():
            try:
                for line in sys.stdin:
                    line = line.strip()
                    if line:
                        loop.call_soon_threadsafe(reader.put_nowait, line)
            except (EOFError, KeyboardInterrupt):
                pass
            finally:
                loop.call_soon_threadsafe(
                    reader.put_nowait, None  # sentinel
                )

        import threading
        t = threading.Thread(target=_stdin_reader, daemon=True)
        t.start()

        while self._running:
            line = await reader.get()
            if line is None:
                break
            try:
                msg = json.loads(line)
                await self.handle(msg)
            except json.JSONDecodeError as e:
                self._write({"id": 0, "ok": False, "error": f"Bad JSON: {e}"})

        # Clean up
        if self.client:
            try:
                await self.client.shutdown()
            except Exception:
                pass


def main():
    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,  # keep stdout for JSON protocol
        format="%(name)s: %(message)s",
    )

    worker = DCWorker()

    # Handle SIGTERM gracefully
    def on_sigterm(*_):
        worker._running = False
    signal.signal(signal.SIGTERM, on_sigterm)

    asyncio.run(worker.run())


if __name__ == "__main__":
    main()
