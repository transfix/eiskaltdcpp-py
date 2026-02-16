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

## Building

```bash
# Configure
cmake -B build -DCMAKE_BUILD_TYPE=Release

# Build
cmake --build build -j$(nproc)

# Run tests
cd build && ctest -V
```

### CMake options

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

Run any example with `--help` to see options:

```bash
python examples/basic_chat.py dchub://your-hub.example.com:411
python examples/search_and_download.py dchub://hub.example.com "ubuntu iso" --auto-download
python examples/download_progress.py dchub://hub.example.com --refresh 1
python examples/file_list_browser.py dchub://hub.example.com SomeUser
python examples/share_manager.py
python examples/multi_hub_bot.py dchub://hub1.example.com dchub://hub2.example.com
```

## Architecture

```
┌──────────────────────────┐
│  Python: DCClient        │  High-level Pythonic API
│  (dc_client.py)          │  Event handlers, context manager
├──────────────────────────┤
│  SWIG: dc_core           │  Auto-generated bindings
│  (dc_core.i)             │  Directors for callbacks, GIL management
├──────────────────────────┤
│  C++: DCBridge           │  Bridge layer
│  (bridge.h/cpp)          │  Listeners → Callbacks routing
├──────────────────────────┤
│  libeiskaltdcpp           │  DC client core library
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
│       └── dc_client.py        # High-level Python wrapper
└── tests/
    ├── CMakeLists.txt          # Test configuration
    └── test_dc_core.py         # pytest tests (concurrency-safe)
```

## License

GPL-3.0-or-later — same as libeiskaltdcpp.
