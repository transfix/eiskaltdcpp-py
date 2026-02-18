# eiskaltdcpp-py

Python SWIG bindings for [libeiskaltdcpp](https://github.com/eiskaltdcpp/eiskaltdcpp) —
a full-featured Direct Connect (NMDC/ADC) client library.

## Overview

This project wraps the eiskaltdcpp core C++ library via SWIG, providing:

- **`dc_core`** — Low-level SWIG module exposing `DCBridge`, `DCClientCallback`, and data types
- **`eiskaltdcpp.DCClient`** — High-level Pythonic wrapper with event handlers and context manager

### Features

- Connect to NMDC and ADC hubs
- Public and private chat
- File search across connected hubs
- Download queue management (including magnet links)
- File list browsing and downloading
- Share directory management
- Transfer monitoring
- File hashing control
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
│  (dcpp/)                 │  NMDC/ADC, search, transfers, hashing
└──────────────────────────┘
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
│   └── multi_hub_bot.py        # Multi-hub bot example
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
│       ├── dc_client.py        # High-level Python wrapper
│       ├── async_client.py     # Async wrapper
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
│               └── status.py   # /api/status/*
└── tests/
    ├── CMakeLists.txt          # Test configuration
    ├── test_dc_core.py         # SWIG binding tests
    ├── test_api.py             # REST API endpoint tests
    ├── test_client.py          # RemoteDCClient unit tests
    ├── test_websocket.py       # WebSocket tests
    ├── test_dashboard.py       # Dashboard tests
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
