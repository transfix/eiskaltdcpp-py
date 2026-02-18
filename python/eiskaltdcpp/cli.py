"""
Unified CLI for eiskaltdcpp-py.

Provides subcommands to launch the DC daemon, the REST API, or both.
Each can run in the foreground (attached) or detached (daemonised).

Usage::

    # Launch daemon attached (stdout/stderr to terminal)
    eispy daemon --config-dir /var/lib/dc

    # Launch daemon detached
    eispy daemon -d --config-dir /var/lib/dc --log-file /var/log/dc.log

    # Launch API attached
    eispy api --admin-pass s3cret --port 9000

    # Launch both daemon + API detached
    eispy up -d --admin-pass s3cret --config-dir /var/lib/dc

    # Stop a detached process
    eispy stop --pid-file /var/run/eiskaltdcpp.pid

    # Show status of running instance
    eispy status
"""
from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import click

logger = logging.getLogger("eiskaltdcpp.cli")

# Default paths
DEFAULT_PID_FILE = "/tmp/eiskaltdcpp.pid"
DEFAULT_LOG_FILE = ""  # empty = stdout/stderr


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
def cli():
    """eispy — eiskaltdcpp-py DC client daemon and REST API.

    Launch the DC client daemon, the REST API, or both from a single
    command.  Each mode supports running attached (foreground) or
    detached (background daemon).

    \b
    Examples:
      eispy daemon --hub dchub://hub.example.com:411
      eispy api --admin-pass s3cret --port 9000
      eispy up --hub dchub://hub.example.com:411 --admin-pass s3cret
      eispy up -d --log-file /var/log/eiskaltdcpp.log
      eispy stop
      eispy status
    """


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


def main():
    """Entry point for console_scripts."""
    cli()


if __name__ == "__main__":
    main()
