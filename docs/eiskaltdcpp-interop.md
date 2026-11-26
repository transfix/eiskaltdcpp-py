# eiskaltdcpp-interop

`eiskaltdcpp-interop` runs one headless EiskaltDC++ client and drives it through JSON lines on
stdin and stdout, so a test can use EiskaltDC++ as a black box: connect it to a hub, chat, list
users, search and download, and read what it sees.

- **Contract version:** 1 (`eiskaltdcpp-interop --version` prints it).
- **Client:** EiskaltDC++ 2.6.2 (the transfix fork), the version the `ready` event reports.
- **Package:** `eiskaltdcpp-py-cp312` on cvcpkg.org (also `-cp311` and `-cp313`), Linux x86_64.

## Install and run

```bash
cvcpkg install eiskaltdcpp-py-cp312 --prefix P
P/bin/eiskaltdcpp-interop --nick alice --share /tmp/a-share --download-dir /tmp/a-dl --passive
```

`P/bin/eiskaltdcpp-interop` runs without activating the prefix. Each prefix holds one Python
column, so install `-cp311`, `-cp312` or `-cp313` into a prefix of its own.

## Command line

```
eiskaltdcpp-interop --nick NICK --share DIR --download-dir DIR
                    [--active --port PORT --ip IP | --passive] [--log FILE]
```

- It starts its own client with a fresh temporary configuration. It reads nothing from
  `~/.config` or the rest of the user's home, and deletes the configuration when it exits.
- It shares `DIR` and hashes it before it reports `ready`.
- `--active`: it accepts peer connections on `--port` (TCP and UDP) and tells peers to connect
  to `--ip`. It also listens for encrypted (TLS) peer connections on a second port, a free one
  picked at start.
- `--passive` (the default when neither is given): it accepts no peer connections.
- `--log FILE`: diagnostics go to FILE (appended). Without it they go to stderr. Nothing but
  contract events is ever written to stdout.
- It exits with status 0 on `{"op":"quit"}`, on EOF on stdin, or on SIGTERM, within 10 s.
  Status 1 means start-up failed (an `error` event with `"op":"start"` says why). Status 2
  means bad arguments.

## Events (stdout)

One JSON object per line, each with `"event"`:

| Event | When |
|---|---|
| `{"event":"ready","version":"2.6.2"}` | Once, after start-up, when the share is hashed. Commands are read only after it. |
| `{"event":"hub","state":"connected","url":URL,"detail":null}` | Logged in to the hub at URL: the hub lists this client's nick. |
| `{"event":"hub","state":"disconnected","url":URL,"detail":TEXT}` | The connection to a hub it had logged in to was lost. |
| `{"event":"hub","state":"redirect","url":URL,"detail":NEW_URL}` | The hub redirected it. It follows: it leaves URL and connects to NEW_URL, and later `hub` events carry NEW_URL. Commands act on NEW_URL from then on. |
| `{"event":"hub","state":"error","url":URL,"detail":TEXT}` | It could not log in: connection refused or failed, TLS keyprint mismatch, nick taken, hub full, or a password was asked for. |
| `{"event":"users","nicks":[...]}` | The reply to `users`: every nick the hub lists, this client's own included, sorted. |
| `{"event":"chat","from":NICK,"text":TEXT}` | Each main-chat line received, including this client's own lines as the hub echoes them. `from` is null for a line with no sender. A third-person line (`/me`) has its text prefixed with `/me `. |
| `{"event":"pm","from":NICK,"text":TEXT}` | Each private message received from another user. |
| `{"event":"result","name":FILE,"size":N,"tth":TTH_OR_NULL,"from":NICK}` | One per search result: a file's name (no directory), its size in bytes, its TTH (39 base32 characters) or null, and the user who has it. Directory results are not reported. |
| `{"event":"downloaded","name":FILE,"path":ABS_PATH,"sha256":HEX}` | A queued download finished. `path` is in `--download-dir`. |
| `{"event":"error","op":OP,"message":TEXT}` | A command failed. `op` is the command's `op`, or `""` for a line that is not a command, or `"start"` for start-up. |

## Commands (stdin)

One JSON object per line, each with `"op"`. Commands run in order. Their effects show up as the
events above, and a command that fails gives an `error` event.

| Command | Does |
|---|---|
| `{"op":"connect","url":URL}` | Connect to a hub. URL is `HOST:PORT` (NMDC, as `127.0.0.1:411`), `dchub://HOST:PORT`, or `nmdcs://HOST:PORT` (NMDC over TLS). For NMDCS, `nmdcs://HOST:PORT/?kp=SHA256/<base32>` pins the hub's keyprint: a different certificate gives a hub `error` with a keyprint mismatch. Without `kp` any certificate is accepted. One hub at a time: a second `connect` leaves the first hub, and gives no event for it. |
| `{"op":"say","text":TEXT}` | Send a main-chat line. |
| `{"op":"pm","to":NICK,"text":TEXT}` | Send a private message. An `error` if NICK is not on the hub. |
| `{"op":"users"}` | Reply with a `users` event. |
| `{"op":"search","pattern":TEXT}` | Search the hub. Results arrive as `result` events, for as long as peers answer. A new search replaces the previous results. |
| `{"op":"download","name":FILE,"from":NICK}` | Queue the file named FILE from NICK, from the latest search's results, by its TTH. A `downloaded` event follows when it finishes. An `error` if no result has that name from that user, or if the result has no TTH. |
| `{"op":"quit"}` | Leave the hub, shut down, exit 0. |

`say`, `pm`, `users`, `search` and `download` need a logged-in hub: before the `hub` event with
`"state":"connected"` they give an `error`.

## Limits

- One hub at a time.
- Downloads go by TTH. A result without one cannot be downloaded (NMDC clients normally send a
  TTH for every file).
- A download that fails is retried by the client; there is no event for a failure. Give up after
  a timeout of your choosing.
- No hub passwords: a hub that asks for one gives a hub `error`.
- Start-up waits up to 300 s for hashing. Files whose names start with `.` are not shared.
- Linux x86_64 only.

## Tested

`tests/interop/check_interop.py` in transfix/eiskaltdcpp-py runs two drivers (one active, one
passive) against an NMDC hub, over NMDC and over NMDCS with a pinned keyprint. It checks login,
`users`, main chat, PMs, search, downloads both ways with matching SHA-256, `error` events, a
wrong keyprint being refused, and exit 0 within 10 s on `quit` and on EOF.
