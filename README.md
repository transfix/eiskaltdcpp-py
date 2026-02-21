# eiskaltdcpp-py

Python SWIG bindings for [libeiskaltdcpp](https://github.com/eiskaltdcpp/eiskaltdcpp) —
a full-featured Direct Connect (NMDC/ADC) client library.

## Overview

This project wraps the eiskaltdcpp core C++ library via SWIG, providing:

- **`dc_core`** — Low-level SWIG module exposing `DCBridge`, `DCClientCallback`, and data types
- **`eiskaltdcpp.DCClient`** — High-level Pythonic wrapper with event handlers and context manager

### Features

- Connect to NMDC and ADC hubs (with TLS encryption support)
- Public and private chat
- File search across connected hubs
- Download queue management (including magnet links)
- File list browsing and downloading
- Share directory management
- Transfer monitoring
- File hashing control
- Embedded Lua scripting with typed exception handling
- Event-driven callback system (hub events, chat, users, transfers, etc.)

## Installation

### From PyPI (recommended)

```bash
pip install eiskaltdcpp-py
```

Pre-built wheels are available for Linux x86_64, Python 3.10–3.13.
All C++ dependencies are bundled — no system packages needed.

### From source (pip)

```bash
# Install build deps first
sudo apt install cmake swig python3-dev libssl-dev zlib1g-dev libbz2-dev

# pip install will compile from source; libeiskaltdcpp is fetched automatically
pip install .
```

### From source (CMake)

```bash
# Install system deps
sudo apt install cmake swig python3-dev libssl-dev zlib1g-dev libbz2-dev \
    libeiskaltdcpp-dev   # optional — built from source if missing

# Configure + build
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)

# Run tests
cd build && ctest -V
```

## Requirements

- **Python** ≥ 3.10
- **CMake** ≥ 3.14
- **SWIG** ≥ 4.0
- **C++17** compiler (GCC 9+, Clang 10+)
- **libeiskaltdcpp** (system package or built from source automatically)

### System dependencies (Ubuntu/Debian)

```bash
sudo apt install \
    cmake swig python3-dev \
    libssl-dev zlib1g-dev libbz2-dev \
    libeiskaltdcpp-dev   # optional — built from source if missing
```

## CMake options

| Option | Default | Description |
|--------|---------|-------------|
| `BUILD_TESTS` | `ON` | Build and register pytest tests |
| `USE_SYSTEM_EISKALTDCPP` | `ON` | Try system `libeiskaltdcpp-dev` first |

If the system package isn't found, CMake automatically fetches and builds
libeiskaltdcpp from source via `FetchContent`.

## Usage

### Quick start

```python
from eiskaltdcpp import DCClient

with DCClient('/tmp/dc-config') as client:
    @client.on('chat_message')
    def on_chat(hub_url, nick, message):
        print(f'<{nick}> {message}')

    @client.on('hub_connected')
    def on_connected(hub_url, hub_name):
        print(f'Connected to {hub_name}')

    client.connect('dchub://example.com:411')

    import time
    time.sleep(60)  # Stay connected for 1 minute
```

### Search and download

```python
client.search('ubuntu iso', file_type=0)

import time
time.sleep(5)  # Wait for results

results = client.get_search_results()
for r in results:
    print(f'{r.fileName} ({r.fileSize} bytes) from {r.nick}')
    if 'ubuntu' in r.fileName.lower():
        client.download('/tmp/downloads', r.fileName, r.fileSize, r.tth)
        break
```

### Share management

```python
client.add_share('/home/user/shared', 'MyFiles')
client.refresh_share()
print(f'Sharing {client.shared_files} files ({client.share_size} bytes)')
```

### Event types

| Event | Arguments |
|-------|-----------|
| `hub_connecting` | `hub_url` |
| `hub_connected` | `hub_url, hub_name` |
| `hub_disconnected` | `hub_url, reason` |
| `hub_redirect` | `hub_url, new_url` |
| `hub_get_password` | `hub_url` |
| `hub_updated` | `hub_url, hub_name` |
| `hub_nick_taken` | `hub_url` |
| `hub_full` | `hub_url` |
| `chat_message` | `hub_url, nick, message` |
| `private_message` | `hub_url, nick, message` |
| `status_message` | `hub_url, message` |
| `user_connected` | `hub_url, user_info` |
| `user_disconnected` | `hub_url, user_info` |
| `user_updated` | `hub_url, user_info` |
| `search_result` | `result_info` |
| `queue_item_added` | `queue_item_info` |
| `queue_item_finished` | `queue_item_info` |
| `queue_item_removed` | `target` |
| `download_starting` | `transfer_info` |
| `download_complete` | `transfer_info` |
| `download_failed` | `transfer_info, reason` |
| `upload_starting` | `transfer_info` |
| `upload_complete` | `transfer_info` |
| `hash_progress` | `current_file, files_left, bytes_left` |

## Examples

The `examples/` directory contains complete, runnable scripts:

| Script | Description |
|--------|-------------|
| [`basic_chat.py`](examples/basic_chat.py) | Connect to a hub, send and receive chat messages, handle PM |
| [`search_and_download.py`](examples/search_and_download.py) | Search for files, display results, queue downloads |
| [`file_list_browser.py`](examples/file_list_browser.py) | Request and interactively browse a user's file list |
| [`download_progress.py`](examples/download_progress.py) | Real-time transfer dashboard with speed, ETA, and progress bars |
| [`share_manager.py`](examples/share_manager.py) | Add/remove/rename shared dirs, monitor hashing |
| [`multi_hub_bot.py`](examples/multi_hub_bot.py) | Bot connecting to multiple hubs with auto-reconnect and chat commands |
| [`remote_client.py`](examples/remote_client.py) | Control a DC client over the REST API using `RemoteDCClient` |

Run any example with `--help` to see options:

```bash
python examples/basic_chat.py dchub://your-hub.example.com:411
python examples/search_and_download.py dchub://hub.example.com "ubuntu iso" --auto-download
python examples/download_progress.py dchub://hub.example.com --refresh 1
python examples/file_list_browser.py dchub://hub.example.com SomeUser
python examples/share_manager.py
python examples/multi_hub_bot.py dchub://hub1.example.com dchub://hub2.example.com
python examples/remote_client.py --url http://localhost:8080 --user admin --pass s3cret
```

## Architecture

```
┌──────────────────────────────────┐
│  RemoteDCClient                  │  Control a running server over HTTP/WS
│  (api/client.py)                 │  Bot / integration friendly
├──────────────────────────────────┤
│  FastAPI REST API + WebSocket    │  JWT auth, RBAC (admin / readonly)
│  (api/)                          │  Dashboard, real-time events
├──────────────────────────────────┤
│  Python: DCClient / AsyncDCClient│  High-level Pythonic API
│  (dc_client.py, async_client.py) │  Event handlers, context manager
├──────────────────────────────────┤
│  SWIG: dc_core                   │  Auto-generated bindings
│  (dc_core.i)                     │  Directors for callbacks, GIL management
├──────────────────────────────────┤
│  C++: DCBridge                   │  Bridge layer
│  (bridge.h/cpp)                  │  Listeners → Callbacks routing
├──────────────────────────────────┤
│  libeiskaltdcpp                  │  DC client core library
│  (dcpp/)                         │  NMDC/ADC, search, transfers, hashing
└──────────────────────────────────┘
```

## CLI

After installing the package (or with `PYTHONPATH=build/python`), a unified
`eispy` command is available.  It can launch the DC daemon, the REST
API, or both — and interactively control a running daemon from the
command line.

### Global options

Every `eispy` invocation accepts these connection options so you can
talk to **any** running daemon, local or remote:

```bash
eispy --url http://10.0.0.5:8080 --user admin --pass s3cret hub ls
```

| Flag | Env variable | Default | Description |
|------|-------------|---------|-------------|
| `--url` | `EISPY_URL` | `http://127.0.0.1:8080` | API base URL |
| `--user` | `EISPY_USER` | `admin` | API username |
| `--pass` | `EISPY_PASS` | `changeme` | API password |
| `--local` | `EISPY_LOCAL` | off | Use a local DC client instead of REST API |
| `--config-dir` | `EISKALTDCPP_CONFIG_DIR` | `~/.eiskaltdcpp-py/` | Config directory for local mode |

### Default config directory

The DC client stores its configuration, settings, certificates, hash
databases, and downloaded file lists in a **config directory**.  The
default location is:

```
~/.eiskaltdcpp-py/
```

If the `$HOME` environment variable is not set, the fallback is
`/tmp/.eiskaltdcpp-py/`.  You can override it with
`--config-dir <path>` or the `EISKALTDCPP_CONFIG_DIR` environment
variable.

The config directory contains:

| File / Directory | Purpose |
|------------------|---------|
| `DCPlusPlus.xml` | All DC++ settings (nick, ports, connection mode, etc.) |
| `Favorites.xml` | Saved hub bookmarks |
| `Queue.xml` | Persistent download queue |
| `HashData/` | Tiger Tree Hash database (speeds up re-hashing) |
| `FileLists/` | Downloaded user file lists |
| `scripts/` | Lua scripts directory (see Lua scripting below) |
| `Certificates/` | TLS certificates for secure hubs |

### Local mode

By default, remote operation commands (`hub`, `chat`, `search`, etc.)
communicate with a running daemon via the REST API.  With `--local`,
they instead spin up a **direct DC client instance** using the native
C++ library — no daemon or API server required:

```bash
# Use a local client with default config dir (~/.eiskaltdcpp-py/)
eispy --local hub ls
eispy --local share ls
eispy --local setting get Nick

# Use a specific config directory
eispy --local --config-dir /var/lib/dc hub ls

# Environment variables work too
export EISPY_LOCAL=1
export EISKALTDCPP_CONFIG_DIR=/var/lib/dc
eispy hub ls
```

> **Note:** Local mode requires the SWIG bindings to be installed
> (i.e. the `dc_core` module must be available).  Some commands like
> `user` (API user management) and `events` (WebSocket streaming) are
> not available in local mode since they depend on the REST API.

### Server commands

| Command  | Description |
|----------|-------------|
| `daemon` | Launch the DC client daemon (connects to hubs, stays alive) |
| `api`    | Launch the REST API server (JWT auth, dashboard) |
| `up`     | Launch **both** daemon + API in a single process |
| `stop`   | Send SIGTERM to a detached instance (via PID file) |
| `status` | Check whether a detached instance is running |

```bash
# Launch the DC daemon attached (stdout/stderr to terminal)
eispy daemon --hub dchub://hub.example.com:411 --nick MyBot

# Launch the REST API attached
eispy api --admin-pass s3cret --port 9000

# Launch both daemon + API together (foreground)
eispy up --hub dchub://hub.example.com:411 --admin-pass s3cret

# Detach any mode with -d  (writes PID file, redirects to log)
eispy up -d --hub dchub://hub:411 --admin-pass s3cret \
  --log-file /var/log/eiskaltdcpp.log

# Check status / stop a background instance
eispy status
eispy stop
```

### Remote operation commands

Once a daemon is running (locally or on a remote host), you can drive
**every** client operation from the `eispy` CLI.  All remote commands
communicate with the daemon over the REST API via `RemoteDCClient`.

#### Hub management (`eispy hub`)

```bash
eispy hub connect dchub://hub.example.com:411        # join a hub
eispy hub connect dchub://hub.example.com --encoding CP1252
eispy hub disconnect dchub://hub.example.com:411      # leave
eispy hub ls                                          # list connected hubs (JSON)
eispy hub users dchub://hub.example.com:411           # list users on a hub
```

#### Chat (`eispy chat`)

```bash
eispy chat send dchub://hub.example.com "Hello world"   # public chat
eispy chat pm dchub://hub.example.com SomeNick "Hi"     # private message
eispy chat history                                       # recent messages
eispy chat history --hub dchub://hub.example.com --limit 50
```

#### Search (`eispy search`)

```bash
eispy search query "ubuntu iso"                  # search all hubs
eispy search query "photo" --file-type 7         # search for pictures
eispy search query "data" --hub dchub://hub:411  # restrict to one hub
eispy search results                              # view results (table)
eispy search results --json                       # machine-readable output
eispy search clear                                # discard results
```

**File types:** 0 = any, 1 = audio, 2 = compressed, 3 = document,
4 = executable, 5 = picture, 6 = video, 7 = directory, 8 = TTH.

#### Download queue (`eispy queue`)

```bash
eispy queue ls                                    # show queued downloads
eispy queue ls --json
eispy queue add /tmp/downloads file.txt 1048576 ABCDEF1234567890  # by TTH
eispy queue add-magnet "magnet:?xt=urn:tree:tiger:..." /tmp/downloads
eispy queue priority /tmp/downloads/file.txt highest
eispy queue rm /tmp/downloads/file.txt
eispy queue clear
```

**Priority values:** `paused`, `lowest`, `low`, `normal`, `high`, `highest`.

#### Shares (`eispy share`)

```bash
eispy share ls                                    # list shared directories
eispy share add /home/user/shared MyFiles         # add a share
eispy share rm MyFiles                            # remove by virtual name
eispy share refresh                               # re-hash all shares
eispy share size                                  # total share size + file count
```

#### Settings (`eispy setting`)

```bash
eispy setting get Nick                            # read a dcpp setting
eispy setting set Nick "MyBot"                    # change a setting
eispy setting reload                              # reload config from disk
eispy setting networking                          # rebind listen ports
```

#### Transfers & hashing (`eispy transfer`)

```bash
eispy transfer stats                              # download/upload speed, totals
eispy transfer hash-status                        # hashing progress
eispy transfer pause-hash                         # pause hashing
eispy transfer resume-hash                        # resume hashing
```

#### File-list browsing (`eispy filelist`)

```bash
eispy filelist request dchub://hub.example.com SomeUser  # request file list
eispy filelist ls dchub://hub.example.com SomeUser       # list root directory
eispy filelist ls dchub://hub.example.com SomeUser /Music
eispy filelist browse dchub://hub.example.com SomeUser   # interactive tree walk
eispy filelist download dchub://hub.example.com SomeUser \
      /Music/song.mp3 /tmp/downloads                     # download a file
eispy filelist download-dir dchub://hub.example.com SomeUser \
      /Music /tmp/downloads                              # download entire dir
eispy filelist close dchub://hub.example.com SomeUser    # free memory
```

#### API user management (`eispy user`)

```bash
eispy user ls                                     # list API accounts
eispy user create viewer p@ssword --role readonly  # create account
eispy user update viewer --role admin              # change role
eispy user rm viewer                               # delete account
```

#### Real-time events (`eispy events`)

```bash
eispy events                                      # all events
eispy events --channels chat,search               # only chat + search
eispy --url http://10.0.0.5:8080 events           # from a remote daemon
```

Events stream until Ctrl-C.

#### Remote shutdown (`eispy shutdown`)

```bash
eispy shutdown                                    # gracefully stop daemon+API
```

#### Lua scripting (`eispy lua`)

```bash
eispy lua status                                  # check Lua availability
eispy lua ls                                      # list scripts in scripts dir
eispy lua eval 'print("hello from lua")'          # evaluate Lua code
eispy lua eval-file /path/to/script.lua           # run a Lua file
```

Lua scripting requires the DC client to be compiled with `LUA_SCRIPT=ON`
(the default for eiskaltdcpp).  Scripts in the config directory's
`scripts/` folder can be run directly.  See **Lua scripting** below for
details.

### Daemon environment variables

| Variable | Option |
|---|---|
| `EISKALTDCPP_CONFIG_DIR` | `--config-dir` |
| `EISKALTDCPP_NICK` | `--nick` |
| `EISKALTDCPP_PASSWORD` | `--password` |
| `EISKALTDCPP_HOST` | `--host` |
| `EISKALTDCPP_PORT` | `--port` |
| `EISKALTDCPP_ADMIN_USER` | `--admin-user` |
| `EISKALTDCPP_ADMIN_PASS` | `--admin-pass` |
| `EISKALTDCPP_JWT_SECRET` | `--jwt-secret` |
| `EISKALTDCPP_USERS_FILE` | `--users-file` |
| `EISKALTDCPP_LOG_FILE` | `--log-file` |
| `EISKALTDCPP_PID_FILE` | `--pid-file` |

### Full option reference

```
eispy --help
eispy daemon -h
eispy api -h
eispy up -h
eispy hub -h
eispy search -h
eispy queue -h
```

## REST API

The project includes a full REST API server that can wrap a running DC client
instance and expose it over HTTP with JWT-authenticated endpoints, WebSocket
event streaming, and a web dashboard.

### Installing API dependencies

```bash
pip install eiskaltdcpp-py[api]
# or from source
pip install .[api]
```

### Launching from the command line

```bash
# Minimal — auto-generates JWT secret, admin/changeme
python -m eiskaltdcpp.api

# Custom admin credentials
python -m eiskaltdcpp.api --admin-user joe --admin-pass s3cret

# Bind to all interfaces, custom port, persist users
python -m eiskaltdcpp.api \
    --host 0.0.0.0 --port 9000 \
    --admin-user joe --admin-pass s3cret \
    --users-file /var/lib/dc/users.json \
    --config-dir /var/lib/dc/config

# Auth-only mode (no DC client, for development / testing)
python -m eiskaltdcpp.api --no-dc-client --admin-pass testing123

# Debug logging
python -m eiskaltdcpp.api --log-level DEBUG --admin-pass s3cret
```

All options can also be set via environment variables:

| Variable | Description |
|----------|-------------|
| `EISKALTDCPP_ADMIN_USER` | Admin username (default: `admin`) |
| `EISKALTDCPP_ADMIN_PASS` | Admin password (required if not set via `--admin-pass`) |
| `EISKALTDCPP_JWT_SECRET` | JWT signing secret (auto-generated if not set) |
| `EISKALTDCPP_CONFIG_DIR` | DC client config directory |
| `EISKALTDCPP_USERS_FILE` | Path to persist API users (JSON) |

### Embedding the API in a Python script

Use `create_app()` to build a configured FastAPI application, then run it
with any ASGI server.  This is ideal for bots and custom integrations:

```python
import uvicorn
from eiskaltdcpp import AsyncDCClient
from eiskaltdcpp.api import create_app

# Create the DC client
dc = AsyncDCClient("/tmp/my-bot-config")

# Build the API app with custom settings
app = create_app(
    dc_client=dc,
    admin_username="botadmin",
    admin_password="hunter2",
    jwt_secret="my-fixed-secret",         # omit to auto-generate
    token_expire_minutes=60,              # 1-hour tokens
    users_file="/tmp/api-users.json",     # persist users across restarts
    cors_origins=["http://localhost:3000"],
)

# Run the server
uvicorn.run(app, host="127.0.0.1", port=8080)
```

You can also skip the DC client entirely for auth-only mode (great for
testing the API or building a front-end before the DC backend is ready):

```python
app = create_app(
    admin_username="admin",
    admin_password="testing123",
)
```

### API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/login` | — | Get a JWT token |
| GET | `/api/auth/users` | admin | List API users |
| POST | `/api/auth/users` | admin | Create a user |
| PUT | `/api/auth/users/{name}` | admin | Update a user |
| DELETE | `/api/auth/users/{name}` | admin | Delete a user |
| POST | `/api/hubs/connect` | admin | Connect to a hub |
| POST | `/api/hubs/disconnect` | admin | Disconnect from a hub |
| GET | `/api/hubs` | any | List connected hubs |
| GET | `/api/hubs/users` | any | List users on a hub |
| POST | `/api/chat/message` | admin | Send a chat message |
| POST | `/api/chat/pm` | admin | Send a private message |
| GET | `/api/chat/history` | any | Get chat history |
| POST | `/api/search` | admin | Start a search |
| GET | `/api/search/results` | any | Get search results |
| DELETE | `/api/search/results` | admin | Clear search results |
| POST | `/api/queue` | admin | Add a download |
| POST | `/api/queue/magnet` | admin | Add a magnet link |
| GET | `/api/queue` | any | List download queue |
| DELETE | `/api/queue` | admin | Clear download queue |
| DELETE | `/api/queue/{target}` | admin | Remove a download |
| PUT | `/api/queue/{target}/priority` | admin | Set download priority |
| GET | `/api/shares` | any | List shared directories |
| POST | `/api/shares` | admin | Add a share directory |
| DELETE | `/api/shares` | admin | Remove a share |
| POST | `/api/shares/refresh` | admin | Refresh share lists |
| GET | `/api/settings/{name}` | any | Get a setting |
| PUT | `/api/settings/{name}` | admin | Set a setting |
| POST | `/api/settings/reload` | admin | Reload configuration |
| POST | `/api/settings/networking` | admin | Rebind network |
| GET | `/api/status` | any | System status |
| GET | `/api/status/transfers` | any | Transfer statistics |
| GET | `/api/status/hashing` | any | Hashing status |
| POST | `/api/status/hashing/pause` | admin | Pause/resume hashing |
| GET | `/api/lua/status` | any | Check Lua availability |
| GET | `/api/lua/scripts` | any | List Lua scripts |
| POST | `/api/lua/eval` | admin | Evaluate Lua code |
| POST | `/api/lua/eval-file` | admin | Run a Lua script file |
| WS | `/ws/events` | token | Real-time event stream |
| GET | `/dashboard` | — | Web dashboard (SPA) |
| GET | `/api/docs` | — | Interactive Swagger UI |
| GET | `/api/redoc` | — | ReDoc documentation |

### RemoteDCClient

`RemoteDCClient` provides a Pythonic async client that mirrors the
`DCClient` / `AsyncDCClient` interface but communicates over HTTP and
WebSocket.  Use it to control a DC client running on another machine or
process:

```python
from eiskaltdcpp.api.client import RemoteDCClient

async def main():
    async with RemoteDCClient(
        "http://localhost:8080",
        username="admin",
        password="s3cret",
    ) as client:
        # Connect to a hub
        await client.connect("dchub://hub.example.com:411")

        # List hubs
        hubs = await client.list_hubs_async()
        for h in hubs:
            print(h.url, h.name, h.user_count)

        # Search
        await client.search_async("ubuntu iso")
        results = await client.get_search_results_async()

        # Real-time events
        async for event, data in client.events("chat,hubs"):
            print(event, data)
```

See [`examples/remote_client.py`](examples/remote_client.py) for a complete
runnable script.

## Practical workflows

Direct Connect operations are inherently **asynchronous** — you issue a
request and results arrive some time later (seconds to minutes depending on
network conditions and hub size).  The sections below walk through the most
common multi-step workflows and call out the timing pitfalls we discovered
while running integration tests against live hubs.

### Browsing a user's shared files

Before you can download individual files from another user you first need
their **file list** (an XML index of everything they share).  This is a
two-phase process:

1. **Request** the file list — the hub tells the remote client to send it.
2. **Wait** for it to arrive, then **browse** or **download** from it.

```bash
# CLI — start the daemon in the background
eispy up -d --hub dchub://hub.example.com:411 --admin-pass s3cret

# Request a specific user's file list
eispy filelist request dchub://hub.example.com SomeUser

# Wait a few seconds for the transfer to complete, then list the root
eispy filelist ls dchub://hub.example.com SomeUser

# Drill into a subdirectory
eispy filelist ls dchub://hub.example.com SomeUser /Music/Rock

# Interactive tree walk — prints dirs and files at each level,
# prompts you to pick a directory to descend into
eispy filelist browse dchub://hub.example.com SomeUser

# Download a single file
eispy filelist download dchub://hub.example.com SomeUser \
      /Music/Rock/song.flac /tmp/downloads

# Download an entire directory (recursive)
eispy filelist download-dir dchub://hub.example.com SomeUser \
      /Music/Rock /tmp/downloads

# Free memory when done
eispy filelist close dchub://hub.example.com SomeUser
```

Programmatically with `AsyncDCClient`:

```python
from eiskaltdcpp import AsyncDCClient
import asyncio, time

async def browse_user():
    async with AsyncDCClient("/tmp/dc-config") as client:
        client.connect("dchub://hub.example.com:411")

        # Wait for the hub connection and user list to populate
        await asyncio.sleep(5)

        # Request the file list
        client.request_filelist("dchub://hub.example.com", "SomeUser")

        # File lists can take a while on slow connections
        for _ in range(30):
            await asyncio.sleep(1)
            items = client.list_filelist("dchub://hub.example.com",
                                         "SomeUser", "/")
            if items:
                break

        for item in items:
            kind = "DIR " if item.get("is_directory") else "FILE"
            print(f"  {kind} {item['name']}  ({item.get('size', '')})")

        # Download a file from the list
        client.download_filelist_entry(
            "dchub://hub.example.com", "SomeUser",
            "/Music/song.flac", "/tmp/downloads",
        )
```

### Search → download workflow

Searching is broadcast to every connected hub.  Results trickle in over
several seconds as remote clients reply.

```bash
# Start a search
eispy search query "ubuntu server iso"

# Wait 5-10 seconds for results to arrive
sleep 5
eispy search results

# Results include file name, size, TTH hash, and source nick.
# Queue a download using the TTH from the results:
eispy queue add /tmp/downloads ubuntu-24.04-live-server-amd64.iso \
      4700000000 ABCDEF1234567890ABCDEF1234567890ABCDEFGH

# Monitor progress
eispy transfer stats
eispy queue ls
```

Programmatically:

```python
client.search("ubuntu iso")
time.sleep(5)

results = client.get_search_results()
for r in results:
    print(f"{r.fileName} ({r.fileSize} bytes) TTH:{r.tth} from {r.nick}")

# Queue the best match
best = results[0]
client.download("/tmp/downloads", best.fileName, best.fileSize, best.tth)
```

### Download queue management

The download queue persists across restarts.  Every queued item has a
**target** path (local destination) which is its unique identifier.

```bash
# List everything in the queue
eispy queue ls --json

# Add by magnet link (typically copied from a web page or chat)
eispy queue add-magnet \
  "magnet:?xt=urn:tree:tiger:ABCDEF...&dn=file.zip&xl=1048576" \
  /tmp/downloads

# Prioritize an important download
eispy queue priority /tmp/downloads/file.zip highest

# Remove a stalled item
eispy queue rm /tmp/downloads/file.zip

# Nuclear option — drop everything
eispy queue clear
```

### Share management and hashing

When you add a directory to your shares, dcpp must **hash** every file
(Tiger Tree Hash) before it can be offered to other users.  On large
shares this can take hours on first run.  Subsequent runs are incremental.

```bash
# Add a share
eispy share add /home/user/Videos Videos

# Trigger a full re-scan
eispy share refresh

# Watch hashing progress
eispy transfer hash-status   # files_left, bytes_left, current_file

# Pause hashing (e.g. to reduce disk I/O during a download)
eispy transfer pause-hash
eispy transfer resume-hash

# Check total share size
eispy share size
```

## Lua scripting

eiskaltdcpp supports embedded Lua scripting when compiled with
`LUA_SCRIPT=ON` (the default).  Lua scripts can interact with the DC
client — sending hub messages, reading settings, and hooking into
events.

### Checking availability

```bash
eispy lua status
# Lua scripting: available
# Scripts path:  /home/user/.eiskaltdcpp-py/scripts/
```

Or via the REST API:

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/lua/status
```

Or in Python:

```python
client.lua_is_available()     # True / False
client.lua_get_scripts_path() # "/home/user/.eiskaltdcpp-py/scripts/"
```

### Running Lua code

```bash
# Evaluate inline code
eispy lua eval 'print("hello from lua")'

# Run a script file
eispy lua eval-file ~/.eiskaltdcpp-py/scripts/myscript.lua
```

Via the API:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"code": "print(\"hello\")"}' \
  http://localhost:8080/api/lua/eval
```

Via Python:

```python
from eiskaltdcpp.exceptions import LuaError, LuaRuntimeError, LuaLoadError

try:
    client.lua_eval('print("hello from lua")')
except LuaRuntimeError as exc:
    print(f"Runtime error: {exc}")
except LuaLoadError as exc:
    print(f"Load error: {exc}")

try:
    client.lua_eval_file("/path/to/script.lua")
except LuaError as exc:
    print(f"Lua error ({type(exc).__name__}): {exc}")
```

### Scripts directory

Lua scripts are stored in `<config_dir>/scripts/`.  List them with:

```bash
eispy lua ls
```

eiskaltdcpp ships with 19 example scripts in `eiskaltdcpp/data/luascripts/`
(antispam, chat formatting, auto-away, etc.).  Copy them to your
scripts directory to use them:

```bash
cp eiskaltdcpp/data/luascripts/*.lua ~/.eiskaltdcpp-py/scripts/
eispy lua ls
```

This project also includes purpose-built examples in `examples/lua/`:

| Script | Description |
|--------|-------------|
| [`chat_logger.lua`](examples/lua/chat_logger.lua) | Log all hub chat to timestamped daily files |
| [`auto_greet.lua`](examples/lua/auto_greet.lua) | Welcome users on join with configurable messages |
| [`chat_commands.lua`](examples/lua/chat_commands.lua) | Custom `/slash` command framework (calc, dice, hubinfo, etc.) |
| [`hub_monitor.lua`](examples/lua/hub_monitor.lua) | Track hub events, user counts, peak stats |
| [`spam_filter.lua`](examples/lua/spam_filter.lua) | Block messages matching configurable keyword patterns |

```bash
# Run an example directly
eispy lua eval-file examples/lua/chat_logger.lua

# Or install to the scripts directory
cp examples/lua/*.lua ~/.eiskaltdcpp-py/scripts/
```

### Lua API available to scripts

When the full ScriptManager is initialized, Lua scripts have access to
the `DC` table with these functions:

| Function | Description |
|----------|-------------|
| `DC:SendHubMessage(hub, msg)` | Send a public chat message |
| `DC:SendClientMessage(hub, nick, msg)` | Send a private message |
| `DC:PrintDebug(msg)` | Print to debug log |
| `DC:GetSetting(name)` | Read a DC setting |
| `DC:GetAppPath()` | Application install path |
| `DC:GetConfigPath()` | Config directory path |
| `DC:GetScriptsPath()` | Scripts directory path |

## Error handling

Lua operations raise typed exceptions instead of returning error strings.
All exception classes live in `eiskaltdcpp.exceptions` and inherit from
`LuaError` (which extends Python's `RuntimeError`):

| Exception | When raised |
|-----------|-------------|
| `LuaError` | Base class for all Lua errors |
| `LuaNotAvailableError` | Lua scripting not compiled in (`LUA_SCRIPT=OFF`) |
| `LuaSymbolError` | Lua C API symbols cannot be resolved at runtime |
| `LuaLoadError` | Lua code failed to parse / compile |
| `LuaRuntimeError` | Lua code compiled but raised an error during execution |

Catch the base class to handle any Lua failure, or catch specific
subclasses for fine-grained control:

```python
from eiskaltdcpp.exceptions import (
    LuaError, LuaNotAvailableError, LuaLoadError, LuaRuntimeError,
)

try:
    client.lua_eval('bad syntax (((')
except LuaLoadError:
    print("Code failed to compile")
except LuaRuntimeError:
    print("Runtime error in Lua")
except LuaNotAvailableError:
    print("Lua not available — recompile with LUA_SCRIPT=ON")
except LuaError as exc:
    print(f"Other Lua error: {exc}")
```

The REST API (`/api/lua/eval`, `/api/lua/eval-file`) returns the exception
type in the `error_type` field of the response body when `ok` is `false`.

## TLS encryption

The DC client supports TLS-encrypted connections to hubs and peers.
When listing connected hubs, each `HubInfo` object exposes TLS status:

| Field | Type | Description |
|-------|------|-------------|
| `is_secure` | `bool` | `True` if the connection uses TLS |
| `is_trusted` | `bool` | `True` if the server certificate is trusted |
| `cipher_name` | `str` | TLS cipher suite name (e.g. `"TLS_AES_256_GCM_SHA384"`) |

```python
for hub in client.list_hubs():
    tls = "TLS" if hub.is_secure else "plain"
    print(f"{hub.hub_name}: {tls} ({hub.cipher_name or 'n/a'})")
```

Connect to TLS-enabled hubs using the `adcs://` (ADC+TLS) or `nmdcs://`
(NMDC+TLS) URL schemes.

## Hashing and timing notes

These are practical lessons learned from integration testing (against
live hubs such as `wintermute.sublevels.net`) and from the automated CI
test suite.

### `HashingStartDelay`

By default dcpp waits **a few seconds** after initialization before it
begins hashing.  For automated tests or short-lived scripts this delay
means the client might shut down before hashing even starts.

Set the setting to `0` as early as possible:

```python
client.set_setting("HashingStartDelay", "0")
```

Or via the CLI:

```bash
eispy setting set HashingStartDelay 0
```

### File list timing

`request_filelist()` is **non-blocking** — it sends a request to the
remote user and returns immediately.  The actual XML file list arrives
asynchronously via a peer-to-peer transfer.  In integration tests we use
a retry loop with exponential back-off:

```python
for attempt in range(15):
    items = client.list_filelist(hub_url, nick, "/")
    if items:
        break
    await asyncio.sleep(min(2 ** attempt * 0.5, 10))
else:
    raise TimeoutError("File list never arrived")
```

Common reasons a file list fails to arrive:

- **User went offline** between the request and the transfer.
- **Passive-passive** — both sides are behind NAT with no port forwarding.
  Use `eispy setting networking` (calls `start_networking()`) to bind
  listen ports, or set `IncomingConnections` to an appropriate mode.
- **Slow connection** — large shares can produce multi-megabyte file lists
  that take a while to transfer and decompress.

### Networking modes

dcpp supports three connection modes:

| `IncomingConnections` | Meaning |
|-----------------------|---------|
| `0` (Passive/Firewall) | Cannot accept incoming — relies on the other side |
| `1` (Direct/Active) | Listens on `InPort` / `TLSPort` |
| `2` (UPnP) | Tries automatic port mapping via UPnP |

For reliable file transfers (especially file-list requests), set Active:

```bash
eispy setting set IncomingConnections 1
eispy setting networking   # apply immediately
```

### Search result timing

Results begin arriving **1–5 seconds** after issuing a search and may
continue trickling in for 10+ seconds depending on hub size.  Searching
too often triggers **flood protection** on many hubs — a 15–30 second
cooldown between searches is recommended.

### Hashing before sharing

Until hashing completes, files in your shares will not appear in other
users' search results.  If you add a share and immediately search for
your own files, you may see zero results.  Monitor `hash-status` and
wait for `files_left == 0`.

### Hub `nick_taken` and reconnection

If your chosen nick is already in use on the hub, the daemon receives a
`hub_nick_taken` event and the connection fails.  When running
automated tests with multiple clients, use unique nicks (e.g. append a
random suffix):

```python
import random, string
suffix = ''.join(random.choices(string.digits, k=4))
client.set_setting("Nick", f"TestBot_{suffix}")
```

## Project structure

```
eiskaltdcpp-py/
├── CMakeLists.txt              # Top-level build (Python, SWIG, deps)
├── pyproject.toml              # Python packaging metadata
├── README.md
├── examples/
│   ├── basic_chat.py           # Hub chat example
│   ├── search_and_download.py  # Search & download example
│   ├── file_list_browser.py    # File list browsing example
│   ├── download_progress.py    # Transfer progress dashboard
│   ├── share_manager.py        # Share management example
│   ├── multi_hub_bot.py        # Multi-hub bot example
│   └── lua/                    # Lua scripting examples
│       ├── chat_logger.lua     # Log hub chat to daily files
│       ├── auto_greet.lua      # Welcome users on join
│       ├── chat_commands.lua   # Custom /slash command framework
│       ├── hub_monitor.lua     # Track hub events & user counts
│       └── spam_filter.lua     # Block messages by keyword pattern
├── src/
│   ├── CMakeLists.txt          # Static bridge library
│   ├── bridge.h                # DCBridge class header
│   ├── bridge.cpp              # DCBridge implementation
│   ├── bridge_listeners.h      # dcpp listener → callback routing
│   ├── bridge_listeners.cpp    # Listener helper methods
│   ├── callbacks.h             # DCClientCallback abstract class
│   └── types.h                 # Data structs (HubInfo, UserInfo, etc.)
├── swig/
│   ├── CMakeLists.txt          # SWIG module build
│   └── dc_core.i               # Master SWIG interface file
├── python/
│   └── eiskaltdcpp/
│       ├── __init__.py         # Package init
│       ├── exceptions.py       # Typed Lua exception hierarchy
│       ├── dc_client.py        # High-level Python wrapper
│       ├── async_client.py     # Async wrapper
│       ├── cli.py              # Unified Click CLI (daemon/api/up/stop/status)
│       └── api/
│           ├── __init__.py     # create_app() factory
│           ├── __main__.py     # CLI: python -m eiskaltdcpp.api
│           ├── app.py          # FastAPI application factory
│           ├── auth.py         # JWT + bcrypt + user store
│           ├── client.py       # RemoteDCClient (HTTP/WS)
│           ├── dashboard.py    # Single-page web dashboard
│           ├── dependencies.py # FastAPI DI configuration
│           ├── models.py       # Pydantic request/response schemas
│           ├── websocket.py    # WebSocket event streaming
│           └── routes/
│               ├── auth.py     # /api/auth/*
│               ├── hubs.py     # /api/hubs/*
│               ├── chat.py     # /api/chat/*
│               ├── search.py   # /api/search/*
│               ├── queue.py    # /api/queue/*
│               ├── shares.py   # /api/shares/*
│               ├── settings.py # /api/settings/*
│               ├── lua.py      # /api/lua/*
│               └── status.py   # /api/status/*
└── tests/
    ├── CMakeLists.txt          # Test configuration
    ├── test_dc_core.py         # SWIG binding tests
    ├── test_cli.py             # CLI subcommand & option tests
    ├── test_api.py             # REST API endpoint tests
    ├── test_client.py          # RemoteDCClient unit tests
    ├── test_websocket.py       # WebSocket tests
    ├── test_dashboard.py       # Dashboard tests
    ├── test_cli_remote.py      # CLI remote + local mode tests
    ├── test_lua_integration.py # Lua scripting integration tests
    ├── test_integration.py     # Live network integration tests
    └── test_remote_client_integration.py  # RemoteDCClient integration
```

## Releasing to PyPI

This project uses [cibuildwheel](https://cibuildwheel.pypa.io/) to build
manylinux wheels and [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC) for upload — no API tokens needed.

### Steps

1. **Update the version** in `pyproject.toml` and `CMakeLists.txt`
2. **Commit and push** to master
3. **Create a git tag**:
   ```bash
   git tag v2.4.3
   git push origin v2.4.3
   ```
4. The `Wheels` workflow automatically:
   - Builds manylinux wheels for CPython 3.10–3.13 (x86_64)
   - Builds a source distribution
   - Publishes everything to PyPI

You can also trigger a wheel build manually via the workflow dispatch button
in GitHub Actions (without publishing).

### One-time PyPI setup

Register the project on PyPI, then configure trusted publishing:

1. Go to https://pypi.org/manage/project/eiskaltdcpp-py/settings/publishing/
2. Add a new publisher:
   - **Owner**: `transfix`
   - **Repository**: `eiskaltdcpp-py`
   - **Workflow**: `wheels.yml`
   - **Environment**: `pypi`

## License

GPL-3.0-or-later — same as libeiskaltdcpp.
