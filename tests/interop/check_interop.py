#!/usr/bin/env python3
"""End-to-end check of eiskaltdcpp-interop against an NMDC hub run as a black box.

    python3 tests/interop/check_interop.py --hub-script PATH/server/tools/run_hub.py \
        [--driver eiskaltdcpp-interop] [--mode nmdc|nmdcs|redirect|all] [--out DIR]

The hub is cy-pca/sublevels's ``server/tools/run_hub.py`` (stdlib only), started with a plain
and a TLS listener; its NMDCS keyprint is read from its stats file. Two drivers join it:

  alice   --active (127.0.0.1, a free port)
  bob     --passive

and each shares one 1 MiB file of random bytes. For each mode the check expects: both ready;
hub connected; each sees the other in ``users``; main chat and a PM arrive; a search finds the
other's file with a TTH; downloads both ways (passive <- active, active <- passive) with the
source's SHA-256; an ``error`` event for a bad download; with NMDCS, a wrong keyprint gives a
hub ``error``. Then alice quits on ``{"op":"quit"}`` and bob on EOF, each with status 0 within
10 s. Last, a second hub that requires TLS redirects a plain login (carol) to its NMDCS address,
and the driver follows it. Exit status 0 when every check passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

RESULTS: list[tuple[str, bool, str]] = []


def check(what: str, ok: bool, detail: object = "") -> bool:
    RESULTS.append((what, bool(ok), str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}: {what}" + (f" ({detail})" if detail and not ok else ""),
          flush=True)
    return bool(ok)


def free_ports(n: int) -> list[int]:
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


class Driver:
    def __init__(self, cmd: list[str], nick: str, root: str, active_port: int | None) -> None:
        self.nick = nick
        self.share = os.path.join(root, f"share-{nick}")
        self.dl = os.path.join(root, f"dl-{nick}")
        os.makedirs(self.share)
        self.file = f"{nick}-payload.bin"
        data = os.urandom(1 << 20)
        with open(os.path.join(self.share, self.file), "wb") as f:
            f.write(data)
        self.sha = hashlib.sha256(data).hexdigest()
        self.log = os.path.join(root, f"{nick}.log")
        args = cmd + ["--nick", nick, "--share", self.share, "--download-dir", self.dl,
                      "--log", self.log]
        args += (["--active", "--port", str(active_port), "--ip", "127.0.0.1"]
                 if active_port else ["--passive"])
        self.events: queue.Queue = queue.Queue()
        self.seen: list[dict] = []
        self.bad_lines: list[str] = []
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.p.stdout:
            try:
                ev = json.loads(line)
                assert isinstance(ev, dict) and isinstance(ev.get("event"), str)
            except (ValueError, AssertionError):
                self.bad_lines.append(line.rstrip("\n"))
                continue
            self.events.put(ev)

    def send(self, obj: dict) -> None:
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def wait(self, pred, timeout: float) -> dict | None:
        """The first event (already seen or new) matching ``pred``; it is consumed."""
        for i, ev in enumerate(self.seen):
            if pred(ev):
                return self.seen.pop(i)
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                ev = self.events.get(timeout=left)
            except queue.Empty:
                break
            if pred(ev):
                return ev
            self.seen.append(ev)
        return None

    def kill(self) -> None:
        if self.p.poll() is None:
            self.p.kill()
            self.p.wait()


def start_hub(hub_script: str, root: str, out: str, tls_required: bool = False):
    nmdc, nmdcs = free_ports(2)
    cert, key = os.path.join(root, "hub.crt"), os.path.join(root, "hub.key")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=127.0.0.1", "-keyout", key, "-out", cert], check=True,
                   capture_output=True)
    stats = os.path.join(root, "hub-stats.json")
    env = dict(os.environ, SUBLEVELS_NMDC_LISTEN=f"127.0.0.1:{nmdc}",
               SUBLEVELS_NMDCS_LISTEN=f"127.0.0.1:{nmdcs}", SUBLEVELS_TLS_CERT=cert,
               SUBLEVELS_TLS_KEY=key, SUBLEVELS_HUB_NAME="eiskaltdcpp-interop check",
               SUBLEVELS_NMDCS_ADDRESS=f"nmdcs://127.0.0.1:{nmdcs}")
    if tls_required:
        env["SUBLEVELS_TLS_REQUIRED"] = "1"
    log = open(os.path.join(out, "hub-tls-required.log" if tls_required else "hub.log"), "w")
    hub = subprocess.Popen([sys.executable, hub_script, "--stats", stats], env=env,
                           stdout=log, stderr=subprocess.STDOUT)
    kp = ""
    end = time.monotonic() + 30
    while time.monotonic() < end and not kp:
        time.sleep(0.2)
        try:
            kp = json.load(open(stats)).get("nmdcs_keyprint", "")
        except (OSError, ValueError):
            pass
    check(f"the hub{' (TLS required)' if tls_required else ''} starts and publishes its NMDCS "
          "keyprint", kp.startswith("SHA256/"), kp)
    return hub, nmdc, nmdcs, kp


def run_mode(cmd: list[str], hub_url: str, bad_url: str | None, root: str, label: str) -> None:
    (pa,) = free_ports(1)
    alice = Driver(cmd, "alice", root, pa)
    bob = Driver(cmd, "bob", root, None)
    t = f"[{label}]"
    try:
        for d in (alice, bob):
            ev = d.wait(lambda e: e["event"] in ("ready", "error"), 180)
            check(f"{t} {d.nick} is ready", ev and ev["event"] == "ready"
                  and isinstance(ev.get("version"), str), ev)
        for d in (alice, bob):
            d.send({"op": "connect", "url": hub_url})
        for d in (alice, bob):
            ev = d.wait(lambda e: e["event"] == "hub", 60)
            check(f"{t} {d.nick} logs in", ev and ev["state"] == "connected"
                  and ev.get("url") == hub_url, ev)

        for d, other in ((alice, bob), (bob, alice)):
            nicks: list = []
            end = time.monotonic() + 20
            while time.monotonic() < end and other.nick not in nicks:
                d.send({"op": "users"})
                ev = d.wait(lambda e: e["event"] in ("users", "error"), 10)
                nicks = (ev or {}).get("nicks") or []
                if other.nick not in nicks:
                    time.sleep(0.5)
            check(f"{t} {d.nick}'s users include {other.nick}", other.nick in nicks, nicks)

        alice.send({"op": "say", "text": f"hello from alice {label}"})
        ev = bob.wait(lambda e: e["event"] == "chat" and e.get("from") == "alice", 15)
        check(f"{t} bob gets alice's main chat", ev and ev["text"] == f"hello from alice {label}", ev)
        bob.send({"op": "pm", "to": "alice", "text": f"psst {label}"})
        ev = alice.wait(lambda e: e["event"] == "pm", 15)
        check(f"{t} alice gets bob's PM", ev and ev.get("from") == "bob"
              and ev["text"] == f"psst {label}", ev)

        for dst, src, how in ((bob, alice, "passive <- active"), (alice, bob, "active <- passive")):
            dst.send({"op": "search", "pattern": src.file.rsplit(".", 1)[0]})
            ev = dst.wait(lambda e: e["event"] == "result" and e.get("name") == src.file
                          and e.get("from") == src.nick, 30)
            check(f"{t} {dst.nick} finds {src.file} by search", ev and ev["size"] == 1 << 20
                  and isinstance(ev.get("tth"), str) and len(ev["tth"]) == 39, ev)
            dst.send({"op": "download", "name": src.file, "from": src.nick})
            ev = dst.wait(lambda e: e["event"] in ("downloaded", "error"), 90)
            ok = (ev and ev["event"] == "downloaded" and ev["name"] == src.file
                  and ev["sha256"] == src.sha and os.path.isabs(ev["path"])
                  and os.path.isfile(ev["path"]))
            if ok:
                with open(ev["path"], "rb") as f:
                    ok = hashlib.sha256(f.read()).hexdigest() == src.sha
            check(f"{t} {dst.nick} downloads {src.file} ({how}), SHA-256 matches", ok, ev)

        bob.send({"op": "download", "name": "no-such-file.bin", "from": "alice"})
        ev = bob.wait(lambda e: e["event"] == "error", 10)
        check(f"{t} a bad download is an error event", ev and ev.get("op") == "download", ev)
        bob.send({"op": "frobnicate"})
        ev = bob.wait(lambda e: e["event"] == "error", 10)
        check(f"{t} an unknown op is an error event", ev and ev.get("op") == "frobnicate", ev)

        if bad_url:
            bob.send({"op": "connect", "url": bad_url})
            ev = bob.wait(lambda e: e["event"] == "hub" and e.get("url") == bad_url, 30)
            check(f"{t} a wrong keyprint is refused", ev and ev["state"] == "error", ev)

        for d, how in ((alice, "quit"), (bob, "EOF")):
            t0 = time.monotonic()
            if how == "quit":
                d.send({"op": "quit"})
            else:
                d.p.stdin.close()
            try:
                code = d.p.wait(timeout=12)
            except subprocess.TimeoutExpired:
                code = None
            took = time.monotonic() - t0
            check(f"{t} {d.nick} exits 0 within 10 s on {how}", code == 0 and took < 10,
                  f"status {code} after {took:.1f} s")
        for d in (alice, bob):
            check(f"{t} {d.nick}'s stdout is only JSON events", not d.bad_lines, d.bad_lines[:5])
    finally:
        for d in (alice, bob):
            d.kill()


def run_redirect(cmd: list[str], hub_script: str, root: str, out: str) -> None:
    """A hub that requires TLS redirects a plain login to its NMDCS address; the driver follows."""
    hub, nmdc, nmdcs, _ = start_hub(hub_script, root, out, tls_required=True)
    carol = Driver(cmd, "carol", root, None)
    t = "[redirect]"
    try:
        ev = carol.wait(lambda e: e["event"] in ("ready", "error"), 180)
        check(f"{t} carol is ready", ev and ev["event"] == "ready", ev)
        plain = f"127.0.0.1:{nmdc}"
        carol.send({"op": "connect", "url": plain})
        ev = carol.wait(lambda e: e["event"] == "hub", 30)
        target = (ev or {}).get("detail") or ""
        check(f"{t} a plain login is redirected to NMDCS", ev and ev["state"] == "redirect"
              and ev["url"] == plain and target.startswith(f"nmdcs://127.0.0.1:{nmdcs}"), ev)
        ev = carol.wait(lambda e: e["event"] == "hub", 30)
        check(f"{t} carol follows it and logs in", ev and ev["state"] == "connected"
              and ev["url"] == target, ev)
        carol.send({"op": "users"})
        ev = carol.wait(lambda e: e["event"] in ("users", "error"), 10)
        check(f"{t} commands act on the new hub", ev and "carol" in (ev.get("nicks") or []), ev)
        carol.send({"op": "quit"})
        try:
            code = carol.p.wait(timeout=12)
        except subprocess.TimeoutExpired:
            code = None
        check(f"{t} carol exits 0 on quit", code == 0, code)
    finally:
        carol.kill()
        hub.terminate()
        try:
            hub.wait(10)
        except subprocess.TimeoutExpired:
            hub.kill()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--hub-script", required=True, help="cy-pca/sublevels server/tools/run_hub.py")
    p.add_argument("--driver", default="eiskaltdcpp-interop", help="driver command (shell words)")
    p.add_argument("--mode", choices=("nmdc", "nmdcs", "redirect", "all"), default="all")
    p.add_argument("--out", default="", help="keep logs here")
    a = p.parse_args()
    cmd = shlex.split(a.driver)
    root = tempfile.mkdtemp(prefix="eiskaltdcpp-interop-check-")
    out = a.out or root
    os.makedirs(out, exist_ok=True)
    hub, nmdc, nmdcs, kp = start_hub(a.hub_script, root, out)
    try:
        modes = ("nmdc", "nmdcs", "redirect") if a.mode == "all" else (a.mode,)
        for m in modes:
            sub = os.path.join(root, m)
            os.makedirs(sub)
            if m == "redirect":
                run_redirect(cmd, a.hub_script, sub, out)
            elif m == "nmdc":
                run_mode(cmd, f"127.0.0.1:{nmdc}", None, sub, m)
            else:
                bad = "SHA256/" + "A" * 52
                run_mode(cmd, f"nmdcs://127.0.0.1:{nmdcs}/?kp={kp}",
                         f"nmdcs://127.0.0.1:{nmdcs}/?kp={bad}", sub, m)
            if out != root:
                for f in ("alice.log", "bob.log", "carol.log"):
                    src = os.path.join(sub, f)
                    if os.path.exists(src):
                        shutil.copy(src, os.path.join(out, f"{m}-{f}"))
    finally:
        hub.terminate()
        try:
            hub.wait(10)
        except subprocess.TimeoutExpired:
            hub.kill()
        if out != root:
            shutil.rmtree(root, ignore_errors=True)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
