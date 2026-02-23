"""
Unified CLI for eiskaltdcpp-py.

Provides subcommands to launch the DC daemon, the REST API, or both,
**and** to interact with a running instance via the REST API.

Usage::

    # Launch daemon + API together
    eispy up --hub dchub://hub.example.com:411 --admin-pass s3cret

    # --- Remote operations (talk to a running daemon) ---

    # Connect to a hub
    eispy hub connect dchub://hub.example.com:411

    # List connected hubs
    eispy hub ls

    # List users on a hub
    eispy hub users dchub://hub.example.com:411

    # Search
    eispy search query "ubuntu iso"
    eispy search results

    # Queue
    eispy queue ls
    eispy queue add-magnet "magnet:?xt=urn:tree:tiger:..."

    # Shares
    eispy share ls
    eispy share add /data/movies Movies

    # Settings
    eispy setting get Nick
    eispy setting set Nick MyBot

    # Transfers
    eispy transfer stats
    eispy transfer hash-status

    # Connect to a remote (non-local) daemon
    eispy --url http://10.0.0.5:8080 --user admin --pass s3cret hub ls
"""
from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import click

from eiskaltdcpp.exceptions import LuaError

logger = logging.getLogger("eiskaltdcpp.cli")

# Default paths / URLs
DEFAULT_PID_FILE = "/tmp/eiskaltdcpp.pid"
DEFAULT_LOG_FILE = ""  # empty = stdout/stderr
DEFAULT_API_URL = "http://localhost:8080"


# ============================================================================
# Helpers
# ============================================================================

def _setup_logging(log_level: str, log_file: str) -> None:
    """Configure root logging."""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = []

    if log_file:
        handlers.append(logging.FileHandler(log_file, mode="a"))
    else:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=fmt,
        handlers=handlers,
        force=True,
    )


def _write_pid(pid_file: str, pid: int) -> None:
    """Write a PID file."""
    path = Path(pid_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))
    atexit.register(lambda: path.unlink(missing_ok=True))


def _read_pid(pid_file: str) -> Optional[int]:
    """Read a PID from a file. Returns None if missing or stale."""
    path = Path(pid_file)
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
        os.kill(pid, 0)  # check if alive
        return pid
    except (ValueError, OSError):
        path.unlink(missing_ok=True)
        return None


def _daemonise(log_file: str, pid_file: str) -> None:
    """Fork into background (Unix double-fork pattern)."""
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent — wait a moment for child to settle, then exit
        click.echo(f"Detached (PID {pid})")
        sys.exit(0)

    # New session
    os.setsid()

    # Second fork to prevent zombie processes
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Redirect file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)  # stdin

    if log_file:
        log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(log_fd, 1)  # stdout
        os.dup2(log_fd, 2)  # stderr
        if log_fd > 2:
            os.close(log_fd)
    else:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)

    if devnull > 2:
        os.close(devnull)

    # Write PID
    _write_pid(pid_file, os.getpid())

    # Re-setup logging after fd redirect
    _setup_logging("INFO", log_file)


# ============================================================================
# Daemon runner
# ============================================================================

def _run_daemon(
    config_dir: str,
    hubs: tuple[str, ...],
    nick: str,
    password: str,
    log_level: str,
) -> None:
    """Run the DC client daemon in the current process (blocking)."""
    import asyncio

    async def _main() -> None:
        from eiskaltdcpp import AsyncDCClient

        logger.info("Starting DC daemon (config: %s)", config_dir or "(default)")

        async with AsyncDCClient(config_dir) as client:
            # Set nick if provided
            if nick:
                client.set_setting("Nick", nick)
                logger.info("Nick set to: %s", nick)

            if password:
                client.set_setting("Password", password)

            # Connect to hubs
            for hub_url in hubs:
                logger.info("Connecting to %s", hub_url)
                await client.connect(hub_url)

            # Log events
            @client.on("hub_connected")
            def on_connected(url, name):
                logger.info("Connected to %s (%s)", name, url)

            @client.on("hub_disconnected")
            def on_disconnected(url, reason):
                logger.warning("Disconnected from %s: %s", url, reason)

            @client.on("chat_message")
            def on_chat(url, nick_, msg, _third):
                logger.debug("[%s] <%s> %s", url, nick_, msg)

            # Wait forever (until signal)
            stop = asyncio.Event()

            def _signal_handler():
                logger.info("Received shutdown signal")
                stop.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _signal_handler)

            logger.info("DC daemon running — press Ctrl-C or send SIGTERM to stop")
            await stop.wait()

        logger.info("DC daemon stopped")

    asyncio.run(_main())


# ============================================================================
# API runner
# ============================================================================

def _run_api(
    host: str,
    port: int,
    admin_user: str,
    admin_pass: str,
    jwt_secret: str,
    token_expire_minutes: int,
    users_file: str,
    cors_origins: tuple[str, ...],
    log_level: str,
    dc_client=None,
) -> None:
    """Run the REST API server in the current process (blocking)."""
    import uvicorn

    from eiskaltdcpp.api.app import create_app

    app = create_app(
        dc_client=dc_client,
        admin_username=admin_user or "admin",
        admin_password=admin_pass,
        jwt_secret=jwt_secret or None,
        token_expire_minutes=token_expire_minutes,
        users_file=users_file or None,
        cors_origins=list(cors_origins) if cors_origins else None,
    )

    logger.info("Starting API server on %s:%d", host, port)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
    )


# ============================================================================
# Combined runner (daemon + API)
# ============================================================================

def _run_both(
    # Daemon options
    config_dir: str,
    hubs: tuple[str, ...],
    nick: str,
    dc_password: str,
    # API options
    host: str,
    port: int,
    admin_user: str,
    admin_pass: str,
    jwt_secret: str,
    token_expire_minutes: int,
    users_file: str,
    cors_origins: tuple[str, ...],
    log_level: str,
) -> None:
    """Run both DC daemon and API server in one process."""
    import asyncio
    import threading

    async def _main() -> None:
        from eiskaltdcpp import AsyncDCClient

        logger.info("Starting DC daemon + API (config: %s)", config_dir or "(default)")

        async with AsyncDCClient(config_dir) as client:
            if nick:
                client.set_setting("Nick", nick)
            if dc_password:
                client.set_setting("Password", dc_password)

            for hub_url in hubs:
                logger.info("Connecting to %s", hub_url)
                await client.connect(hub_url)

            @client.on("hub_connected")
            def on_connected(url, name):
                logger.info("Connected to %s (%s)", name, url)

            @client.on("hub_disconnected")
            def on_disconnected(url, reason):
                logger.warning("Disconnected from %s: %s", url, reason)

            # Start API server in a background thread
            api_thread = threading.Thread(
                target=_run_api,
                kwargs={
                    "host": host,
                    "port": port,
                    "admin_user": admin_user,
                    "admin_pass": admin_pass,
                    "jwt_secret": jwt_secret,
                    "token_expire_minutes": token_expire_minutes,
                    "users_file": users_file,
                    "cors_origins": cors_origins,
                    "log_level": log_level,
                    "dc_client": client,
                },
                daemon=True,
                name="api-server",
            )
            api_thread.start()
            logger.info("API server starting on %s:%d", host, port)

            # Wait for shutdown signal
            stop = asyncio.Event()

            def _signal_handler():
                logger.info("Received shutdown signal")
                stop.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _signal_handler)

            logger.info("DC daemon + API running — Ctrl-C or SIGTERM to stop")
            await stop.wait()

        logger.info("Shutdown complete")

    asyncio.run(_main())


# ============================================================================
# Click CLI
# ============================================================================

# Shared options via a decorator
def _common_options(fn):
    """Add common options to a Click command."""
    fn = click.option(
        "-d", "--detach", is_flag=True, default=False,
        help="Detach and run in the background.",
    )(fn)
    fn = click.option(
        "--log-file", default="", envvar="EISKALTDCPP_LOG_FILE",
        help="Log to file (default: stdout/stderr). Env: EISKALTDCPP_LOG_FILE",
    )(fn)
    fn = click.option(
        "--pid-file", default=DEFAULT_PID_FILE, envvar="EISKALTDCPP_PID_FILE",
        help=f"PID file path (default: {DEFAULT_PID_FILE}). Env: EISKALTDCPP_PID_FILE",
    )(fn)
    fn = click.option(
        "--log-level", default="INFO",
        type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
        help="Log level (default: INFO).",
    )(fn)
    return fn


def _daemon_options(fn):
    """Add DC daemon options to a Click command."""
    fn = click.option(
        "--config-dir", default="", envvar="EISKALTDCPP_CONFIG_DIR",
        help="DC client config directory. Env: EISKALTDCPP_CONFIG_DIR",
    )(fn)
    fn = click.option(
        "--hub", "hubs", multiple=True,
        help="Hub URL to connect to (can be repeated).",
    )(fn)
    fn = click.option(
        "--nick", default="", envvar="EISKALTDCPP_NICK",
        help="DC nick. Env: EISKALTDCPP_NICK",
    )(fn)
    fn = click.option(
        "--password", "dc_password", default="", envvar="EISKALTDCPP_PASSWORD",
        help="DC hub password. Env: EISKALTDCPP_PASSWORD",
    )(fn)
    return fn


def _api_options(fn):
    """Add REST API options to a Click command."""
    fn = click.option(
        "--host", default="127.0.0.1", envvar="EISKALTDCPP_HOST",
        help="API bind address (default: 127.0.0.1). Env: EISKALTDCPP_HOST",
    )(fn)
    fn = click.option(
        "--port", default=8080, type=int, envvar="EISKALTDCPP_PORT",
        help="API bind port (default: 8080). Env: EISKALTDCPP_PORT",
    )(fn)
    fn = click.option(
        "--admin-user", default="admin", envvar="EISKALTDCPP_ADMIN_USER",
        help="Admin username (default: admin). Env: EISKALTDCPP_ADMIN_USER",
    )(fn)
    fn = click.option(
        "--admin-pass", default="", envvar="EISKALTDCPP_ADMIN_PASS",
        help="Admin password. Env: EISKALTDCPP_ADMIN_PASS",
    )(fn)
    fn = click.option(
        "--jwt-secret", default="", envvar="EISKALTDCPP_JWT_SECRET",
        help="JWT signing secret (auto-generated if not set). Env: EISKALTDCPP_JWT_SECRET",
    )(fn)
    fn = click.option(
        "--token-expire-minutes", default=1440, type=int,
        help="JWT token lifetime in minutes (default: 1440 = 24h).",
    )(fn)
    fn = click.option(
        "--users-file", default="", envvar="EISKALTDCPP_USERS_FILE",
        help="Persist API users to JSON file. Env: EISKALTDCPP_USERS_FILE",
    )(fn)
    fn = click.option(
        "--cors-origin", "cors_origins", multiple=True,
        help="Allowed CORS origins (can be repeated).",
    )(fn)
    return fn


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(package_name="eiskaltdcpp-py", prog_name="eispy")
@click.option(
    "--url", default="", envvar="EISPY_URL",
    help=f"API server URL (default: {DEFAULT_API_URL}). Env: EISPY_URL",
)
@click.option(
    "--user", "api_user", default="", envvar="EISPY_USER",
    help="API username. Env: EISPY_USER",
)
@click.option(
    "--pass", "api_pass", default="", envvar="EISPY_PASS",
    help="API password. Env: EISPY_PASS",
)
@click.option(
    "--local", "local_mode", is_flag=True, default=False,
    envvar="EISPY_LOCAL",
    help="Use a local DC client instance instead of the REST API. Env: EISPY_LOCAL",
)
@click.option(
    "--config-dir", "cli_config_dir", default="",
    envvar="EISKALTDCPP_CONFIG_DIR",
    help="DC config directory for local mode (default: ~/.eiskaltdcpp-py/). "
         "Env: EISKALTDCPP_CONFIG_DIR",
)
@click.pass_context
def cli(ctx, url, api_user, api_pass, local_mode, cli_config_dir):
    """eispy — eiskaltdcpp-py DC client daemon and REST API.

    \b
    Service commands:
      eispy daemon   Launch the DC client daemon
      eispy api      Launch the REST API server
      eispy up       Launch both daemon + API together
      eispy stop     Stop a detached process
      eispy status   Show status of a running instance

    \b
    Remote operations (talk to a running daemon via REST API):
      eispy hub      Hub connections (connect, disconnect, list, users)
      eispy chat     Chat messages (send, pm, history)
      eispy search   Search the DC network (query, results, clear)
      eispy queue    Download queue (ls, add, add-magnet, rm, clear, priority)
      eispy share    Shared directories (ls, add, rm, refresh, size)
      eispy setting  Settings (get, set, reload, networking)
      eispy transfer Transfer and hashing status
      eispy filelist Browse user file lists (request, ls, browse, download)
      eispy lua      Lua scripting (eval, eval-file, ls, status)

    \b
    Local mode (direct DC client, no REST API required):
      eispy --local hub ls
      eispy --local --config-dir /var/lib/dc share ls
      Default config directory: ~/.eiskaltdcpp-py/

    \b
    Remote connection options (for remote operations):
      --url    API server URL (default: http://localhost:8080)
      --user   API username
      --pass   API password
      These can also be set via EISPY_URL, EISPY_USER, EISPY_PASS env vars.

    \b
    Examples:
      eispy up --hub dchub://hub:411 --admin-pass s3cret
      eispy hub ls
      eispy --url http://10.0.0.5:8080 --user admin --pass s3cret hub ls
      eispy --local hub ls
      eispy --local --config-dir /tmp/dc setting get Nick
      eispy search query "ubuntu iso" --hub dchub://hub:411
      eispy queue ls
      eispy share add /data/movies Movies
      eispy lua eval 'print("hello from lua")'
      eispy lua ls
    """
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = url or DEFAULT_API_URL
    ctx.obj["api_user"] = api_user
    ctx.obj["api_pass"] = api_pass
    ctx.obj["local_mode"] = local_mode
    ctx.obj["config_dir"] = cli_config_dir


@cli.command()
@_common_options
@_daemon_options
def daemon(detach, log_file, pid_file, log_level,
           config_dir, hubs, nick, dc_password):
    """Launch the DC client daemon.

    Starts an AsyncDCClient that connects to the specified hubs and
    runs until SIGTERM / Ctrl-C.

    \b
    Examples:
      eispy daemon --hub dchub://hub.example.com:411
      eispy daemon -d --hub dchub://hub1:411 --hub dchub://hub2:411
      eispy daemon --nick MyBot --config-dir /var/lib/dc
    """
    _setup_logging(log_level, log_file)

    if detach:
        if not log_file:
            log_file = "/tmp/eiskaltdcpp-daemon.log"
            click.echo(f"No --log-file set; logging to {log_file}")
        _daemonise(log_file, pid_file)

    _run_daemon(config_dir, hubs, nick, dc_password, log_level)


@cli.command()
@_common_options
@_api_options
def api(detach, log_file, pid_file, log_level,
        host, port, admin_user, admin_pass, jwt_secret,
        token_expire_minutes, users_file, cors_origins):
    """Launch the REST API server.

    Starts a FastAPI/Uvicorn server that exposes the DC client over
    HTTP with JWT authentication.  Without --config-dir or a live DC
    daemon, runs in auth-only mode (useful for development).

    \b
    Examples:
      eispy api --admin-pass s3cret
      eispy api --host 0.0.0.0 --port 9000 --admin-pass s3cret
      eispy api -d --admin-pass s3cret --log-file /var/log/dc-api.log
    """
    _setup_logging(log_level, log_file)

    if detach:
        if not log_file:
            log_file = "/tmp/eiskaltdcpp-api.log"
            click.echo(f"No --log-file set; logging to {log_file}")
        _daemonise(log_file, pid_file)

    _run_api(host, port, admin_user, admin_pass, jwt_secret,
             token_expire_minutes, users_file, cors_origins, log_level)


@cli.command()
@_common_options
@_daemon_options
@_api_options
def up(detach, log_file, pid_file, log_level,
       config_dir, hubs, nick, dc_password,
       host, port, admin_user, admin_pass, jwt_secret,
       token_expire_minutes, users_file, cors_origins):
    """Launch both the DC daemon and REST API together.

    Starts the DC client daemon with an embedded API server in the
    same process.  The API server connects to the live DC client
    instance, providing full control over connecting hubs, chat,
    search, and downloads.

    \b
    Examples:
      eispy up --hub dchub://hub:411 --admin-pass s3cret
      eispy up -d --config-dir /var/lib/dc --admin-pass s3cret
    """
    _setup_logging(log_level, log_file)

    if detach:
        if not log_file:
            log_file = "/tmp/eiskaltdcpp.log"
            click.echo(f"No --log-file set; logging to {log_file}")
        _daemonise(log_file, pid_file)

    _run_both(
        config_dir, hubs, nick, dc_password,
        host, port, admin_user, admin_pass, jwt_secret,
        token_expire_minutes, users_file, cors_origins, log_level,
    )


@cli.command()
@click.option("--pid-file", default=DEFAULT_PID_FILE,
              envvar="EISKALTDCPP_PID_FILE",
              help="PID file to read.")
def stop(pid_file):
    """Stop a detached eispy process.

    Sends SIGTERM to the process recorded in the PID file.
    """
    pid = _read_pid(pid_file)
    if pid is None:
        click.echo(f"No running process found (PID file: {pid_file})")
        raise SystemExit(1)

    click.echo(f"Sending SIGTERM to PID {pid}...")
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait a moment for clean shutdown
        for _ in range(30):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                click.echo("Process stopped.")
                Path(pid_file).unlink(missing_ok=True)
                return
        click.echo("Process did not stop within 3s — sending SIGKILL")
        os.kill(pid, signal.SIGKILL)
        Path(pid_file).unlink(missing_ok=True)
    except ProcessLookupError:
        click.echo("Process already gone.")
        Path(pid_file).unlink(missing_ok=True)
    except PermissionError:
        click.echo(f"Permission denied — try: sudo kill {pid}")
        raise SystemExit(1)


@cli.command()
@click.option("--pid-file", default=DEFAULT_PID_FILE,
              envvar="EISKALTDCPP_PID_FILE",
              help="PID file to check.")
@click.option("--api-url", default="",
              help="API server URL to health-check (e.g. http://localhost:8080).")
def status(pid_file, api_url):
    """Show status of a running eispy instance.

    Checks whether a process is running (via PID file) and optionally
    pings the API health endpoint.
    """
    pid = _read_pid(pid_file)
    if pid is not None:
        click.echo(f"DC daemon running (PID {pid})")
    else:
        click.echo(f"DC daemon not running (PID file: {pid_file})")

    if api_url:
        try:
            import httpx
            resp = httpx.get(f"{api_url.rstrip('/')}/api/status", timeout=5)
            data = resp.json()
            click.echo(f"API server: OK (version {data.get('version', '?')})")
        except Exception as exc:
            click.echo(f"API server: unreachable ({exc})")


# ============================================================================
# Remote-operation helpers
# ============================================================================

class _LocalClientAdapter:
    """Wraps AsyncDCClient to provide the same async method names as RemoteDCClient.

    This allows CLI commands to work identically with either a remote
    (REST API) client or a direct local DC client instance.
    """

    def __init__(self, config_dir: str = ""):
        self._config_dir = config_dir
        self._client = None

    async def __aenter__(self):
        from eiskaltdcpp import AsyncDCClient
        self._client = AsyncDCClient(self._config_dir)
        await self._client.initialize()
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.shutdown()
            self._client = None

    # ---- Hub ----
    async def connect(self, url, encoding=""):
        await self._client.connect(url, encoding)

    async def disconnect(self, url):
        await self._client.disconnect(url)

    async def list_hubs_async(self):
        return self._client.list_hubs()

    async def is_connected_async(self, url):
        return self._client.is_connected(url)

    async def get_users_async(self, hub_url):
        return self._client.get_users(hub_url)

    # ---- Chat ----
    async def send_message_async(self, hub_url, message):
        self._client.send_message(hub_url, message)

    async def send_pm_async(self, hub_url, nick, message):
        self._client.send_pm(hub_url, nick, message)

    async def get_chat_history_async(self, hub_url, max_lines=50):
        return self._client.get_chat_history(hub_url, max_lines)

    # ---- Search ----
    async def search_async(self, terms, file_type=0, size_mode=0,
                           size=0, hub_url=""):
        return self._client.search(terms, file_type, size_mode, size, hub_url)

    async def get_search_results_async(self, hub_url=""):
        return self._client.get_search_results(hub_url)

    async def clear_search_results_async(self, hub_url=""):
        self._client.clear_search_results(hub_url)

    # ---- Queue ----
    async def list_queue_async(self):
        return self._client.list_queue()

    async def download_async(self, directory, name, size, tth,
                             hub_url="", nick=""):
        return self._client.download(directory, name, size, tth)

    async def download_magnet_async(self, magnet, download_dir=""):
        return self._client.download_magnet(magnet, download_dir)

    async def remove_download_async(self, target):
        self._client.remove_download(target)

    async def clear_queue_async(self):
        self._client.clear_queue()

    async def set_priority_async(self, target, level):
        self._client.set_priority(target, level)

    # ---- Shares ----
    async def list_shares_async(self):
        return self._client.list_shares()

    async def add_share_async(self, real_path, virtual_name):
        return self._client.add_share(real_path, virtual_name)

    async def remove_share_async(self, real_path):
        return self._client.remove_share(real_path)

    async def refresh_share_async(self):
        self._client.refresh_share()

    async def get_share_size(self):
        return self._client.share_size

    async def get_shared_files(self):
        return self._client.shared_files

    # ---- Settings ----
    async def get_setting_async(self, name):
        return self._client.get_setting(name)

    async def set_setting_async(self, name, value):
        self._client.set_setting(name, value)

    async def reload_config_async(self):
        self._client.reload_config()

    async def start_networking_async(self):
        self._client.start_networking()

    # ---- Transfers & Hashing ----
    async def get_transfer_stats(self):
        return self._client.transfer_stats

    async def get_hash_status(self):
        return self._client.hash_status

    async def pause_hashing_async(self, pause=True):
        self._client.pause_hashing(pause)

    # ---- Lua scripting ----
    async def lua_is_available_async(self):
        return self._client.lua_is_available()

    async def lua_eval_async(self, code):
        self._client.lua_eval(code)

    async def lua_eval_file_async(self, path):
        self._client.lua_eval_file(path)

    async def lua_get_scripts_path_async(self):
        return self._client.lua_get_scripts_path()

    async def lua_list_scripts_async(self):
        return self._client.lua_list_scripts()

    # ---- Status / lifecycle ----
    async def shutdown(self):
        await self._client.shutdown()

    # ---- User management (not available in local mode) ----
    async def list_users(self):
        click.echo("User management is only available via the REST API", err=True)
        return []

    async def create_user(self, *a, **kw):
        raise click.ClickException("User management is only available via the REST API")

    async def delete_user(self, *a, **kw):
        raise click.ClickException("User management is only available via the REST API")

    async def update_user(self, *a, **kw):
        raise click.ClickException("User management is only available via the REST API")

    # ---- Events (not available in local mode without long-running process) ----
    def events(self, channels="events"):
        raise click.ClickException(
            "Event streaming in local mode is not supported. "
            "Use 'eispy up' to start a daemon, then 'eispy events'."
        )


def _get_remote_client(ctx: click.Context):
    """Create a RemoteDCClient from CLI context (lazy import)."""
    from eiskaltdcpp.api.client import RemoteDCClient

    url = ctx.obj["api_url"]
    user = ctx.obj["api_user"]
    password = ctx.obj["api_pass"]
    return RemoteDCClient(url, username=user, password=password)


def _get_client(ctx: click.Context):
    """Get the appropriate client based on --local flag.

    Returns an async context manager that provides a client object
    with consistent async method names (matching RemoteDCClient).
    In local mode, uses _LocalClientAdapter wrapping AsyncDCClient.
    In remote mode, uses RemoteDCClient.
    """
    if ctx.obj.get("local_mode"):
        config_dir = ctx.obj.get("config_dir", "")
        return _LocalClientAdapter(config_dir)
    return _get_remote_client(ctx)


def _run(coro):
    """Run an async coroutine in a new event loop."""
    return asyncio.run(coro)


def _print_json(data):
    """Print data as formatted JSON."""
    click.echo(json.dumps(data, indent=2, default=str))


def _print_table(rows: list[dict], columns: list[str] | None = None):
    """Print a list of dicts as a simple aligned table."""
    if not rows:
        click.echo("(empty)")
        return
    if columns is None:
        columns = list(rows[0].keys())
    # Compute column widths
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    click.echo(header)
    click.echo("  ".join("-" * widths[c] for c in columns))
    for row in rows:
        line = "  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns)
        click.echo(line)


def _obj_to_dict(obj) -> dict:
    """Convert a dataclass or object with __dict__ to a plain dict."""
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return {"value": str(obj)}


def _format_size(n: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PiB"


# ============================================================================
# hub — Hub connections
# ============================================================================

@cli.group()
def hub():
    """Manage hub connections.

    \b
    Examples:
      eispy hub connect dchub://hub.example.com:411
      eispy hub disconnect dchub://hub.example.com:411
      eispy hub ls
      eispy hub users dchub://hub.example.com:411
    """


@hub.command("connect")
@click.argument("url")
@click.option("--encoding", default="", help="Text encoding (e.g. CP1252).")
@click.pass_context
def hub_connect(ctx, url, encoding):
    """Connect to a DC hub."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.connect(url, encoding)
            click.echo(f"Connected to {url}")
    _run(_do())


@hub.command("disconnect")
@click.argument("url")
@click.pass_context
def hub_disconnect(ctx, url):
    """Disconnect from a DC hub."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.disconnect(url)
            click.echo(f"Disconnected from {url}")
    _run(_do())


@hub.command("ls")
@click.pass_context
def hub_list(ctx):
    """List connected hubs."""
    async def _do():
        async with _get_client(ctx) as client:
            hubs = await client.list_hubs_async()
            if not hubs:
                click.echo("No hubs connected")
                return
            rows = [_obj_to_dict(h) for h in hubs]
            _print_table(rows, ["url", "name", "user_count"])
    _run(_do())


@hub.command("users")
@click.argument("hub_url")
@click.pass_context
def hub_users(ctx, hub_url):
    """List users on a hub."""
    async def _do():
        async with _get_client(ctx) as client:
            users = await client.get_users_async(hub_url)
            if not users:
                click.echo("No users found")
                return
            rows = [_obj_to_dict(u) for u in users]
            cols = ["nick", "share_size", "hub_url"]
            # Use whatever columns are available
            if rows:
                available = list(rows[0].keys())
                cols = [c for c in cols if c in available] or available[:5]
            _print_table(rows, cols)
    _run(_do())


# ============================================================================
# chat — Chat messages
# ============================================================================

@cli.group()
def chat():
    """Send and read chat messages.

    \b
    Examples:
      eispy chat send dchub://hub:411 "Hello everyone!"
      eispy chat pm dchub://hub:411 SomeUser "Hi there"
      eispy chat history dchub://hub:411
    """


@chat.command("send")
@click.argument("hub_url")
@click.argument("message")
@click.pass_context
def chat_send(ctx, hub_url, message):
    """Send a public chat message to a hub."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.send_message_async(hub_url, message)
            click.echo("Message sent")
    _run(_do())


@chat.command("pm")
@click.argument("hub_url")
@click.argument("nick")
@click.argument("message")
@click.pass_context
def chat_pm(ctx, hub_url, nick, message):
    """Send a private message to a user."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.send_pm_async(hub_url, nick, message)
            click.echo(f"PM sent to {nick}")
    _run(_do())


@chat.command("history")
@click.argument("hub_url")
@click.option("-n", "--lines", default=50, help="Max lines to retrieve.")
@click.pass_context
def chat_history(ctx, hub_url, lines):
    """Show chat history for a hub."""
    async def _do():
        async with _get_client(ctx) as client:
            history = await client.get_chat_history_async(hub_url, max_lines=lines)
            for line in history:
                click.echo(line)
    _run(_do())


# ============================================================================
# search — Search the DC network
# ============================================================================

@cli.group()
def search():
    """Search the DC network for files.

    \b
    Examples:
      eispy search query "ubuntu iso"
      eispy search query "movie.mkv" --type 1 --hub dchub://hub:411
      eispy search results
      eispy search results --json
      eispy search clear
    """


@search.command("query")
@click.argument("terms")
@click.option("--type", "file_type", default=0, type=int,
              help="File type (0=any, 1=audio, 2=compressed, 3=document, "
                   "4=executable, 5=picture, 6=video, 7=directory, 8=TTH).")
@click.option("--size-mode", default=0, type=int,
              help="Size filter mode (0=at least, 1=at most, 2=exact).")
@click.option("--size", default=0, type=int, help="Size filter value in bytes.")
@click.option("--hub", "hub_url", default="", help="Limit to a specific hub.")
@click.pass_context
def search_query(ctx, terms, file_type, size_mode, size, hub_url):
    """Search for files on connected hubs."""
    async def _do():
        async with _get_client(ctx) as client:
            ok = await client.search_async(
                terms, file_type=file_type, size_mode=size_mode,
                size=size, hub_url=hub_url,
            )
            if ok:
                click.echo(f"Search sent: {terms}")
                click.echo("Use 'eispy search results' to view results (allow a few seconds).")
            else:
                click.echo("Search failed", err=True)
                raise SystemExit(1)
    _run(_do())


@search.command("results")
@click.option("--hub", "hub_url", default="", help="Filter by hub URL.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def search_results(ctx, hub_url, as_json):
    """Show search results."""
    async def _do():
        async with _get_client(ctx) as client:
            results = await client.get_search_results_async(hub_url)
            if as_json:
                _print_json([_obj_to_dict(r) for r in results])
            elif not results:
                click.echo("No results")
            else:
                rows = [_obj_to_dict(r) for r in results]
                cols = ["filename", "size", "tth", "nick", "hub_url"]
                available = list(rows[0].keys()) if rows else []
                cols = [c for c in cols if c in available] or available[:5]
                _print_table(rows, cols)
    _run(_do())


@search.command("clear")
@click.option("--hub", "hub_url", default="", help="Clear for specific hub only.")
@click.pass_context
def search_clear(ctx, hub_url):
    """Clear search results."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.clear_search_results_async(hub_url)
            click.echo("Search results cleared")
    _run(_do())


# ============================================================================
# queue — Download queue
# ============================================================================

@cli.group()
def queue():
    """Manage the download queue.

    \b
    Examples:
      eispy queue ls
      eispy queue ls --json
      eispy queue add-magnet "magnet:?xt=urn:tree:tiger:..."
      eispy queue add --dir /path --name file.txt --size 1024 --tth ABC123
      eispy queue rm /path/to/target
      eispy queue clear
      eispy queue priority /path/to/target 4
    """


@queue.command("ls")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def queue_list(ctx, as_json):
    """List items in the download queue."""
    async def _do():
        async with _get_client(ctx) as client:
            items = await client.list_queue_async()
            if as_json:
                _print_json([_obj_to_dict(i) for i in items])
            elif not items:
                click.echo("Queue is empty")
            else:
                rows = [_obj_to_dict(i) for i in items]
                cols = ["target", "size", "downloaded", "priority", "tth"]
                available = list(rows[0].keys()) if rows else []
                cols = [c for c in cols if c in available] or available[:5]
                _print_table(rows, cols)
    _run(_do())


@queue.command("add")
@click.option("--dir", "directory", required=True, help="Remote directory path.")
@click.option("--name", required=True, help="File name.")
@click.option("--size", required=True, type=int, help="File size in bytes.")
@click.option("--tth", required=True, help="TTH hash.")
@click.option("--hub", "hub_url", default="", help="Hub URL (for source hint).")
@click.option("--nick", default="", help="Source nick.")
@click.pass_context
def queue_add(ctx, directory, name, size, tth, hub_url, nick):
    """Add a file to the download queue by details."""
    async def _do():
        async with _get_client(ctx) as client:
            ok = await client.download_async(
                directory, name, size, tth, hub_url=hub_url, nick=nick,
            )
            if ok:
                click.echo(f"Queued: {name}")
            else:
                click.echo("Failed to add to queue", err=True)
                raise SystemExit(1)
    _run(_do())


@queue.command("add-magnet")
@click.argument("magnet")
@click.option("--download-dir", default="", help="Download directory override.")
@click.pass_context
def queue_add_magnet(ctx, magnet, download_dir):
    """Add a magnet link to the download queue."""
    async def _do():
        async with _get_client(ctx) as client:
            ok = await client.download_magnet_async(magnet, download_dir)
            if ok:
                click.echo("Magnet queued")
            else:
                click.echo("Failed to add magnet", err=True)
                raise SystemExit(1)
    _run(_do())


@queue.command("rm")
@click.argument("target")
@click.pass_context
def queue_remove(ctx, target):
    """Remove an item from the download queue."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.remove_download_async(target)
            click.echo(f"Removed: {target}")
    _run(_do())


@queue.command("clear")
@click.pass_context
def queue_clear(ctx):
    """Clear the entire download queue."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.clear_queue_async()
            click.echo("Queue cleared")
    _run(_do())


@queue.command("priority")
@click.argument("target")
@click.argument("level", type=int)
@click.pass_context
def queue_priority(ctx, target, level):
    """Set download priority for a queued item.

    Priority levels: 0=paused, 1=lowest, 2=low, 3=normal, 4=high, 5=highest.
    """
    async def _do():
        async with _get_client(ctx) as client:
            await client.set_priority_async(target, level)
            click.echo(f"Priority set to {level}")
    _run(_do())


# ============================================================================
# share — Shared directories
# ============================================================================

@cli.group()
def share():
    """Manage shared directories.

    \b
    Examples:
      eispy share ls
      eispy share add /data/movies Movies
      eispy share rm /data/movies
      eispy share refresh
      eispy share size
    """


@share.command("ls")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def share_list(ctx, as_json):
    """List shared directories."""
    async def _do():
        async with _get_client(ctx) as client:
            shares = await client.list_shares_async()
            if as_json:
                _print_json([_obj_to_dict(s) for s in shares])
            elif not shares:
                click.echo("No shares configured")
            else:
                rows = [_obj_to_dict(s) for s in shares]
                cols = ["virtual_name", "real_path", "size"]
                available = list(rows[0].keys()) if rows else []
                cols = [c for c in cols if c in available] or available[:4]
                _print_table(rows, cols)
    _run(_do())


@share.command("add")
@click.argument("real_path")
@click.argument("virtual_name")
@click.pass_context
def share_add(ctx, real_path, virtual_name):
    """Share a directory with a virtual name.

    \b
    Example: eispy share add /data/movies Movies
    """
    async def _do():
        async with _get_client(ctx) as client:
            ok = await client.add_share_async(real_path, virtual_name)
            if ok:
                click.echo(f"Shared: {real_path} as '{virtual_name}'")
            else:
                click.echo("Failed to add share", err=True)
                raise SystemExit(1)
    _run(_do())


@share.command("rm")
@click.argument("real_path")
@click.pass_context
def share_remove(ctx, real_path):
    """Remove a shared directory."""
    async def _do():
        async with _get_client(ctx) as client:
            ok = await client.remove_share_async(real_path)
            if ok:
                click.echo(f"Removed share: {real_path}")
            else:
                click.echo("Failed to remove share", err=True)
                raise SystemExit(1)
    _run(_do())


@share.command("refresh")
@click.pass_context
def share_refresh(ctx):
    """Refresh the file hash list for all shares."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.refresh_share_async()
            click.echo("Share refresh started")
    _run(_do())


@share.command("size")
@click.pass_context
def share_size(ctx):
    """Show total share size and file count."""
    async def _do():
        async with _get_client(ctx) as client:
            size = await client.get_share_size()
            files = await client.get_shared_files()
            click.echo(f"Share size:  {_format_size(size)} ({size:,} bytes)")
            click.echo(f"File count:  {files:,}")
    _run(_do())


# ============================================================================
# setting — Settings management
# ============================================================================

@cli.group()
def setting():
    """Read and write DC client settings.

    \b
    Examples:
      eispy setting get Nick
      eispy setting set Nick MyBot
      eispy setting set DownloadDirectory /data/downloads
      eispy setting reload
      eispy setting networking
    """


@setting.command("get")
@click.argument("name")
@click.pass_context
def setting_get(ctx, name):
    """Get the value of a setting."""
    async def _do():
        async with _get_client(ctx) as client:
            value = await client.get_setting_async(name)
            click.echo(f"{name} = {value}")
    _run(_do())


@setting.command("set")
@click.argument("name")
@click.argument("value")
@click.pass_context
def setting_set(ctx, name, value):
    """Set a setting value."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.set_setting_async(name, value)
            click.echo(f"{name} = {value}")
    _run(_do())


@setting.command("reload")
@click.pass_context
def setting_reload(ctx):
    """Reload settings from config files."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.reload_config_async()
            click.echo("Config reloaded")
    _run(_do())


@setting.command("networking")
@click.pass_context
def setting_networking(ctx):
    """Rebind network listeners (active mode ports, etc.)."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.start_networking_async()
            click.echo("Networking restarted")
    _run(_do())


# ============================================================================
# transfer — Transfer stats and hashing
# ============================================================================

@cli.group()
def transfer():
    """View transfer statistics and hashing status.

    \b
    Examples:
      eispy transfer stats
      eispy transfer hash-status
      eispy transfer pause-hash
      eispy transfer resume-hash
    """


@transfer.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def transfer_stats(ctx, as_json):
    """Show current transfer statistics."""
    async def _do():
        async with _get_client(ctx) as client:
            stats = await client.get_transfer_stats()
            d = _obj_to_dict(stats)
            if as_json:
                _print_json(d)
            else:
                for k, v in d.items():
                    if "speed" in k.lower():
                        click.echo(f"  {k}: {_format_size(int(v))}/s")
                    elif "size" in k.lower() or "bytes" in k.lower():
                        click.echo(f"  {k}: {_format_size(int(v))}")
                    else:
                        click.echo(f"  {k}: {v}")
    _run(_do())


@transfer.command("hash-status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def transfer_hash_status(ctx, as_json):
    """Show hashing progress."""
    async def _do():
        async with _get_client(ctx) as client:
            hs = await client.get_hash_status()
            d = _obj_to_dict(hs)
            if as_json:
                _print_json(d)
            else:
                for k, v in d.items():
                    if "bytes" in k.lower() or "size" in k.lower():
                        click.echo(f"  {k}: {_format_size(int(v))}")
                    else:
                        click.echo(f"  {k}: {v}")
    _run(_do())


@transfer.command("pause-hash")
@click.pass_context
def transfer_pause_hash(ctx):
    """Pause hashing."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.pause_hashing_async(pause=True)
            click.echo("Hashing paused")
    _run(_do())


@transfer.command("resume-hash")
@click.pass_context
def transfer_resume_hash(ctx):
    """Resume hashing."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.pause_hashing_async(pause=False)
            click.echo("Hashing resumed")
    _run(_do())


# ============================================================================
# filelist — File list browsing and downloads
# ============================================================================

@cli.group()
def filelist():
    """Browse user file lists and download from them.

    File lists let you browse another user's shared files and selectively
    download files or entire directories.

    \b
    Workflow:
      1. Request a file list:  eispy filelist request dchub://hub:411 UserNick
      2. List available lists:  eispy filelist ls
      3. Browse:  eispy filelist browse <list-id> /
      4. Download a file:  eispy filelist download <list-id> /path/to/file.txt
      5. Download a dir:  eispy filelist download-dir <list-id> /Videos
      6. Close:  eispy filelist close <list-id>

    \b
    Note: File list operations are performed via the local DC client
    (not the REST API), since file lists are not yet exposed over HTTP.
    This command requires the Python SWIG bindings to be available.
    """


@filelist.command("request")
@click.argument("hub_url")
@click.argument("nick")
@click.option("--match-queue", is_flag=True, help="Match files against download queue.")
@click.pass_context
def filelist_request(ctx, hub_url, nick, match_queue):
    """Request a user's file list."""
    from eiskaltdcpp import AsyncDCClient

    async def _do():
        # For file list ops we need the direct client, not the remote API
        config_dir = os.environ.get("EISKALTDCPP_CONFIG_DIR", "")
        async with AsyncDCClient(config_dir) as client:
            ok = client.request_file_list(hub_url, nick, match_queue=match_queue)
            if ok:
                click.echo(f"File list requested from {nick}")
                click.echo("Wait a moment, then use 'eispy filelist ls' to see available lists.")
            else:
                click.echo("Failed to request file list", err=True)
                raise SystemExit(1)
    _run(_do())


@filelist.command("ls")
@click.pass_context
def filelist_list(ctx):
    """List locally available file lists."""
    from eiskaltdcpp import AsyncDCClient

    async def _do():
        config_dir = os.environ.get("EISKALTDCPP_CONFIG_DIR", "")
        async with AsyncDCClient(config_dir) as client:
            lists = client.list_local_file_lists()
            if not lists:
                click.echo("No file lists available")
                return
            click.echo("Available file lists:")
            for fl in lists:
                click.echo(f"  {fl}")
    _run(_do())


@filelist.command("browse")
@click.argument("list_id")
@click.option("--dir", "directory", default="/", help="Directory to browse (default: /).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def filelist_browse(ctx, list_id, directory, as_json):
    """Browse a file list directory."""
    from eiskaltdcpp import AsyncDCClient

    async def _do():
        config_dir = os.environ.get("EISKALTDCPP_CONFIG_DIR", "")
        async with AsyncDCClient(config_dir) as client:
            if not client.open_file_list(list_id):
                click.echo(f"Failed to open file list: {list_id}", err=True)
                raise SystemExit(1)
            try:
                entries = client.browse_file_list(list_id, directory)
                if as_json:
                    _print_json([_obj_to_dict(e) for e in entries])
                elif not entries:
                    click.echo(f"Empty directory: {directory}")
                else:
                    rows = [_obj_to_dict(e) for e in entries]
                    cols = ["name", "size", "tth", "type"]
                    available = list(rows[0].keys()) if rows else []
                    cols = [c for c in cols if c in available] or available[:5]
                    _print_table(rows, cols)
            finally:
                client.close_file_list(list_id)
    _run(_do())


@filelist.command("download")
@click.argument("list_id")
@click.argument("file_path")
@click.option("--to", "download_to", default="", help="Local download directory.")
@click.pass_context
def filelist_download(ctx, list_id, file_path, download_to):
    """Download a file from a file list."""
    from eiskaltdcpp import AsyncDCClient

    async def _do():
        config_dir = os.environ.get("EISKALTDCPP_CONFIG_DIR", "")
        async with AsyncDCClient(config_dir) as client:
            if not client.open_file_list(list_id):
                click.echo(f"Failed to open file list: {list_id}", err=True)
                raise SystemExit(1)
            try:
                ok = client.download_from_list(list_id, file_path, download_to)
                if ok:
                    click.echo(f"Queued download: {file_path}")
                else:
                    click.echo("Failed to queue download", err=True)
                    raise SystemExit(1)
            finally:
                client.close_file_list(list_id)
    _run(_do())


@filelist.command("download-dir")
@click.argument("list_id")
@click.argument("dir_path")
@click.option("--to", "download_to", default="", help="Local download directory.")
@click.pass_context
def filelist_download_dir(ctx, list_id, dir_path, download_to):
    """Download an entire directory from a file list."""
    from eiskaltdcpp import AsyncDCClient

    async def _do():
        config_dir = os.environ.get("EISKALTDCPP_CONFIG_DIR", "")
        async with AsyncDCClient(config_dir) as client:
            if not client.open_file_list(list_id):
                click.echo(f"Failed to open file list: {list_id}", err=True)
                raise SystemExit(1)
            try:
                ok = client.download_dir_from_list(list_id, dir_path, download_to)
                if ok:
                    click.echo(f"Queued directory download: {dir_path}")
                else:
                    click.echo("Failed to queue directory download", err=True)
                    raise SystemExit(1)
            finally:
                client.close_file_list(list_id)
    _run(_do())


@filelist.command("close")
@click.argument("list_id")
@click.pass_context
def filelist_close(ctx, list_id):
    """Close an open file list."""
    from eiskaltdcpp import AsyncDCClient

    async def _do():
        config_dir = os.environ.get("EISKALTDCPP_CONFIG_DIR", "")
        async with AsyncDCClient(config_dir) as client:
            client.close_file_list(list_id)
            click.echo(f"File list closed: {list_id}")
    _run(_do())


# ============================================================================
# lua — Lua scripting
# ============================================================================

@cli.group()
def lua():
    """Lua scripting commands.

    Evaluate Lua code, run script files, and manage the scripts directory.
    When the DC client is compiled with LUA_SCRIPT support, Lua scripts
    can interact with hubs, chat, settings, and more via the DC Lua API.

    \b
    Examples:
      eispy lua status
      eispy lua ls
      eispy lua eval 'print("hello from lua")'
      eispy lua eval-file /path/to/script.lua
    """


@lua.command("status")
@click.pass_context
def lua_status(ctx):
    """Check if Lua scripting is available."""
    async def _do():
        async with _get_client(ctx) as client:
            available = await client.lua_is_available_async()
            if available:
                path = await client.lua_get_scripts_path_async()
                click.echo(f"Lua scripting: available")
                click.echo(f"Scripts path:  {path}")
            else:
                click.echo("Lua scripting: not available")
                click.echo("(library not compiled with LUA_SCRIPT)")
    _run(_do())


@lua.command("ls")
@click.pass_context
def lua_list_scripts(ctx):
    """List Lua script files in the scripts directory."""
    async def _do():
        async with _get_client(ctx) as client:
            scripts = await client.lua_list_scripts_async()
            if not scripts:
                path = await client.lua_get_scripts_path_async()
                click.echo(f"No scripts found in {path}")
                return
            for s in scripts:
                click.echo(f"  {s}")
    _run(_do())


@lua.command("eval")
@click.argument("code")
@click.pass_context
def lua_eval(ctx, code):
    """Evaluate a Lua code chunk.

    \b
    Examples:
      eispy lua eval 'print("hello")'
      eispy lua eval 'return 1+2'
    """
    async def _do():
        async with _get_client(ctx) as client:
            try:
                await client.lua_eval_async(code)
                click.echo("OK")
            except LuaError as exc:
                click.echo(f"Lua error ({type(exc).__name__}): {exc}", err=True)
                raise SystemExit(1)
    _run(_do())


@lua.command("eval-file")
@click.argument("path", type=click.Path())
@click.pass_context
def lua_eval_file(ctx, path):
    """Evaluate a Lua script file.

    \b
    Examples:
      eispy lua eval-file myscript.lua
      eispy lua eval-file /path/to/script.lua
    """
    async def _do():
        async with _get_client(ctx) as client:
            try:
                await client.lua_eval_file_async(path)
                click.echo(f"OK — executed {path}")
            except LuaError as exc:
                click.echo(f"Lua error ({type(exc).__name__}): {exc}", err=True)
                raise SystemExit(1)
    _run(_do())


# ============================================================================
# user — API user management
# ============================================================================

@cli.group("user")
def user_group():
    """Manage API user accounts.

    \b
    Examples:
      eispy user ls
      eispy user create viewer p@ssword --role readonly
      eispy user rm viewer
    """


@user_group.command("ls")
@click.pass_context
def user_list(ctx):
    """List API user accounts."""
    async def _do():
        async with _get_client(ctx) as client:
            users = await client.list_users()
            if not users:
                click.echo("No users")
                return
            _print_table(users, ["username", "role"])
    _run(_do())


@user_group.command("create")
@click.argument("username")
@click.argument("password")
@click.option("--role", default="readonly",
              type=click.Choice(["admin", "readonly"], case_sensitive=False),
              help="User role (default: readonly).")
@click.pass_context
def user_create(ctx, username, password, role):
    """Create a new API user."""
    async def _do():
        async with _get_client(ctx) as client:
            result = await client.create_user(username, password, role)
            click.echo(f"Created user: {result.get('username', username)} (role: {role})")
    _run(_do())


@user_group.command("rm")
@click.argument("username")
@click.pass_context
def user_remove(ctx, username):
    """Delete an API user."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.delete_user(username)
            click.echo(f"Deleted user: {username}")
    _run(_do())


@user_group.command("update")
@click.argument("username")
@click.option("--password", default=None, help="New password.")
@click.option("--role", default=None,
              type=click.Choice(["admin", "readonly"], case_sensitive=False),
              help="New role.")
@click.pass_context
def user_update(ctx, username, password, role):
    """Update an API user's password or role."""
    if password is None and role is None:
        click.echo("Specify --password and/or --role", err=True)
        raise SystemExit(1)

    async def _do():
        async with _get_client(ctx) as client:
            result = await client.update_user(username, password=password, role=role)
            click.echo(f"Updated user: {result.get('username', username)}")
    _run(_do())


# ============================================================================
# events — Stream real-time events
# ============================================================================

@cli.command("events")
@click.option("--channels", default="events",
              help="Comma-separated event channels (events,chat,search,transfers,hubs,status).")
@click.pass_context
def stream_events(ctx, channels):
    """Stream real-time events from the daemon via WebSocket.

    \b
    Examples:
      eispy events
      eispy events --channels chat,search
      eispy --url http://10.0.0.5:8080 events --channels hubs,transfers
    """
    async def _do():
        async with _get_client(ctx) as client:
            click.echo(f"Streaming events (channels: {channels}) — Ctrl-C to stop")
            try:
                async for event, data in client.events(channels=channels):
                    ts = time.strftime("%H:%M:%S")
                    click.echo(f"[{ts}] {event}: {json.dumps(data, default=str)}")
            except KeyboardInterrupt:
                pass
            click.echo("\nStopped.")
    _run(_do())


# ============================================================================
# shutdown — Graceful server shutdown
# ============================================================================

@cli.command("shutdown")
@click.pass_context
def remote_shutdown(ctx):
    """Send a graceful shutdown request to the running daemon+API."""
    async def _do():
        async with _get_client(ctx) as client:
            await client.shutdown()
            click.echo("Shutdown request sent")
    _run(_do())


def main():
    """Entry point for console_scripts."""
    cli()


if __name__ == "__main__":
    main()