"""
Tests for the unified CLI (cli.py).

Covers:
- Click group and subcommand structure
- --help output for all subcommands
- Daemon / API / up option parsing
- Detach logic (mocked fork)
- PID file read/write/cleanup
- Stop command (mocked kill)
- Status command output
- Logging setup
"""
from __future__ import annotations

import os
import signal
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from eiskaltdcpp.cli import (
    DEFAULT_PID_FILE,
    _read_pid,
    _setup_logging,
    _write_pid,
    cli,
)


@pytest.fixture
def runner():
    return CliRunner()


# ============================================================================
# Group / help tests
# ============================================================================

class TestCLIGroup:
    """Top-level CLI group structure."""

    def test_cli_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "daemon" in result.output
        assert "api" in result.output
        assert "up" in result.output
        assert "stop" in result.output
        assert "status" in result.output

    def test_cli_short_help(self, runner):
        result = runner.invoke(cli, ["-h"])
        assert result.exit_code == 0

    def test_cli_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        # May fail if package not installed (dev build), but option is recognized
        assert result.exit_code in (0, 1)

    def test_no_subcommand(self, runner):
        result = runner.invoke(cli, [])
        # Click returns 2 when no subcommand given (missing argument)
        assert result.exit_code in (0, 2)


# ============================================================================
# Daemon subcommand
# ============================================================================

class TestDaemonCommand:
    """eiskaltdcpp daemon subcommand."""

    def test_daemon_help(self, runner):
        result = runner.invoke(cli, ["daemon", "--help"])
        assert result.exit_code == 0
        assert "--config-dir" in result.output
        assert "--hub" in result.output
        assert "--nick" in result.output
        assert "--detach" in result.output
        assert "--log-file" in result.output
        assert "--pid-file" in result.output
        assert "--log-level" in result.output

    @patch("eiskaltdcpp.cli._run_daemon")
    def test_daemon_foreground(self, mock_run, runner):
        result = runner.invoke(cli, [
            "daemon", "--hub", "dchub://test:411", "--nick", "Bot",
        ])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][1] == ("dchub://test:411",)  # hubs
        assert args[0][2] == "Bot"  # nick

    @patch("eiskaltdcpp.cli._run_daemon")
    def test_daemon_multiple_hubs(self, mock_run, runner):
        result = runner.invoke(cli, [
            "daemon",
            "--hub", "dchub://hub1:411",
            "--hub", "dchub://hub2:411",
        ])
        assert result.exit_code == 0
        hubs = mock_run.call_args[0][1]
        assert hubs == ("dchub://hub1:411", "dchub://hub2:411")

    @patch("eiskaltdcpp.cli._run_daemon")
    def test_daemon_config_dir(self, mock_run, runner):
        result = runner.invoke(cli, [
            "daemon", "--config-dir", "/var/lib/dc",
        ])
        assert result.exit_code == 0
        assert mock_run.call_args[0][0] == "/var/lib/dc"

    @patch("eiskaltdcpp.cli._run_daemon")
    def test_daemon_log_level(self, mock_run, runner):
        result = runner.invoke(cli, [
            "daemon", "--log-level", "DEBUG",
        ])
        assert result.exit_code == 0
        assert mock_run.call_args[0][4] == "DEBUG"


# ============================================================================
# API subcommand
# ============================================================================

class TestAPICommand:
    """eiskaltdcpp api subcommand."""

    def test_api_help(self, runner):
        result = runner.invoke(cli, ["api", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--admin-user" in result.output
        assert "--admin-pass" in result.output
        assert "--jwt-secret" in result.output
        assert "--users-file" in result.output
        assert "--detach" in result.output

    @patch("eiskaltdcpp.cli._run_api")
    def test_api_foreground(self, mock_run, runner):
        result = runner.invoke(cli, [
            "api", "--admin-pass", "s3cret", "--port", "9000",
        ])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        kwargs = mock_run.call_args
        assert kwargs[0][1] == 9000  # port
        assert kwargs[0][3] == "s3cret"  # admin_pass

    @patch("eiskaltdcpp.cli._run_api")
    def test_api_custom_host(self, mock_run, runner):
        result = runner.invoke(cli, [
            "api", "--host", "0.0.0.0", "--admin-pass", "pass",
        ])
        assert result.exit_code == 0
        assert mock_run.call_args[0][0] == "0.0.0.0"

    @patch("eiskaltdcpp.cli._run_api")
    def test_api_cors_origins(self, mock_run, runner):
        result = runner.invoke(cli, [
            "api", "--cors-origin", "http://localhost:3000",
            "--cors-origin", "http://example.com",
        ])
        assert result.exit_code == 0
        cors = mock_run.call_args[0][7]
        assert "http://localhost:3000" in cors
        assert "http://example.com" in cors


# ============================================================================
# Up subcommand (daemon + API)
# ============================================================================

class TestUpCommand:
    """eiskaltdcpp up subcommand."""

    def test_up_help(self, runner):
        result = runner.invoke(cli, ["up", "--help"])
        assert result.exit_code == 0
        # Should have both daemon and API options
        assert "--hub" in result.output
        assert "--admin-pass" in result.output
        assert "--config-dir" in result.output
        assert "--port" in result.output

    @patch("eiskaltdcpp.cli._run_both")
    def test_up_foreground(self, mock_run, runner):
        result = runner.invoke(cli, [
            "up",
            "--hub", "dchub://hub:411",
            "--admin-pass", "s3cret",
            "--port", "9000",
        ])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("eiskaltdcpp.cli._run_both")
    def test_up_all_options(self, mock_run, runner):
        result = runner.invoke(cli, [
            "up",
            "--config-dir", "/etc/dc",
            "--hub", "dchub://h:411",
            "--nick", "Bot",
            "--host", "0.0.0.0",
            "--port", "7000",
            "--admin-user", "root",
            "--admin-pass", "pass",
        ])
        assert result.exit_code == 0
        args = mock_run.call_args[0]
        assert args[0] == "/etc/dc"  # config_dir
        assert args[2] == "Bot"  # nick
        assert args[4] == "0.0.0.0"  # host
        assert args[5] == 7000  # port
        assert args[6] == "root"  # admin_user


# ============================================================================
# Stop subcommand
# ============================================================================

class TestStopCommand:
    """eiskaltdcpp stop subcommand."""

    def test_stop_help(self, runner):
        result = runner.invoke(cli, ["stop", "--help"])
        assert result.exit_code == 0
        assert "--pid-file" in result.output

    def test_stop_no_pidfile(self, runner, tmp_path):
        result = runner.invoke(cli, [
            "stop", "--pid-file", str(tmp_path / "nonexistent.pid"),
        ])
        assert result.exit_code != 0
        assert "No running process" in result.output

    @patch("os.kill")
    def test_stop_running_process(self, mock_kill, runner, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")

        # kill(pid, 0) for alive check → success
        # kill(pid, SIGTERM) → success
        # kill(pid, 0) second call → process gone
        call_count = 0
        
        def side_effect(pid, sig):
            nonlocal call_count
            call_count += 1
            if sig == 0 and call_count > 2:
                raise OSError("No such process")

        mock_kill.side_effect = side_effect

        result = runner.invoke(cli, ["stop", "--pid-file", str(pid_file)])
        assert "SIGTERM" in result.output or "stopped" in result.output.lower()

    def test_stop_stale_pidfile(self, runner, tmp_path):
        pid_file = tmp_path / "stale.pid"
        pid_file.write_text("999999999")  # very unlikely to exist
        result = runner.invoke(cli, ["stop", "--pid-file", str(pid_file)])
        assert "No running process" in result.output or "already gone" in result.output.lower()


# ============================================================================
# Status subcommand
# ============================================================================

class TestStatusCommand:
    """eiskaltdcpp status subcommand."""

    def test_status_help(self, runner):
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0

    def test_status_no_process(self, runner, tmp_path):
        result = runner.invoke(cli, [
            "status", "--pid-file", str(tmp_path / "none.pid"),
        ])
        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    def test_status_running(self, runner, tmp_path):
        pid_file = tmp_path / "test.pid"
        # Use our own PID so the alive check passes
        pid_file.write_text(str(os.getpid()))
        result = runner.invoke(cli, ["status", "--pid-file", str(pid_file)])
        assert result.exit_code == 0
        assert "running" in result.output.lower()
        assert str(os.getpid()) in result.output


# ============================================================================
# PID file helpers
# ============================================================================

class TestPIDHelpers:
    """_write_pid / _read_pid helpers."""

    def test_write_and_read(self, tmp_path):
        pid_file = str(tmp_path / "test.pid")
        _write_pid(pid_file, os.getpid())
        assert _read_pid(pid_file) == os.getpid()

    def test_read_nonexistent(self, tmp_path):
        assert _read_pid(str(tmp_path / "nope.pid")) is None

    def test_read_stale(self, tmp_path):
        pid_file = tmp_path / "stale.pid"
        pid_file.write_text("999999999")
        assert _read_pid(str(pid_file)) is None

    def test_read_bad_content(self, tmp_path):
        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not-a-number")
        assert _read_pid(str(pid_file)) is None

    def test_write_creates_dirs(self, tmp_path):
        pid_file = str(tmp_path / "sub" / "dir" / "test.pid")
        _write_pid(pid_file, 42)
        assert Path(pid_file).read_text() == "42"


# ============================================================================
# Logging setup
# ============================================================================

class TestLoggingSetup:
    """_setup_logging helper."""

    def test_setup_stderr(self):
        _setup_logging("INFO", "")
        # Should not raise

    def test_setup_file(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        _setup_logging("DEBUG", log_file)
        import logging
        logging.getLogger("test_cli_setup").info("hello")
        assert Path(log_file).exists()


# ============================================================================
# Detach logic (mocked)
# ============================================================================

class TestDetach:
    """Detach (-d) option with mocked fork."""

    @patch("eiskaltdcpp.cli._run_daemon")
    @patch("eiskaltdcpp.cli._daemonise")
    def test_daemon_detach_calls_daemonise(self, mock_daemon, mock_run, runner):
        result = runner.invoke(cli, [
            "daemon", "-d", "--hub", "dchub://hub:411",
        ])
        assert result.exit_code == 0
        mock_daemon.assert_called_once()

    @patch("eiskaltdcpp.cli._run_api")
    @patch("eiskaltdcpp.cli._daemonise")
    def test_api_detach_calls_daemonise(self, mock_daemon, mock_run, runner):
        result = runner.invoke(cli, ["api", "-d"])
        assert result.exit_code == 0
        mock_daemon.assert_called_once()

    @patch("eiskaltdcpp.cli._run_both")
    @patch("eiskaltdcpp.cli._daemonise")
    def test_up_detach_calls_daemonise(self, mock_daemon, mock_run, runner):
        result = runner.invoke(cli, ["up", "-d"])
        assert result.exit_code == 0
        mock_daemon.assert_called_once()

    @patch("eiskaltdcpp.cli._run_daemon")
    def test_no_detach_skips_daemonise(self, mock_run, runner):
        """Without -d, _daemonise should NOT be called."""
        with patch("eiskaltdcpp.cli._daemonise") as mock_d:
            result = runner.invoke(cli, ["daemon"])
            mock_d.assert_not_called()

    @patch("eiskaltdcpp.cli._run_daemon")
    @patch("eiskaltdcpp.cli._daemonise")
    def test_detach_default_logfile(self, mock_daemon, mock_run, runner):
        """When -d is used without --log-file, a default is set."""
        result = runner.invoke(cli, ["daemon", "-d"])
        assert result.exit_code == 0
        assert "logging to" in result.output.lower()


# ============================================================================
# Environment variable support
# ============================================================================

class TestEnvVars:
    """Options fall back to environment variables."""

    @patch("eiskaltdcpp.cli._run_daemon")
    def test_config_dir_envvar(self, mock_run, runner):
        result = runner.invoke(cli, ["daemon"], env={
            "EISKALTDCPP_CONFIG_DIR": "/env/config",
        })
        assert result.exit_code == 0
        assert mock_run.call_args[0][0] == "/env/config"

    @patch("eiskaltdcpp.cli._run_api")
    def test_api_envvars(self, mock_run, runner):
        result = runner.invoke(cli, ["api"], env={
            "EISKALTDCPP_HOST": "0.0.0.0",
            "EISKALTDCPP_PORT": "9999",
            "EISKALTDCPP_ADMIN_USER": "envadmin",
            "EISKALTDCPP_ADMIN_PASS": "envpass",
        })
        assert result.exit_code == 0
        args = mock_run.call_args[0]
        assert args[0] == "0.0.0.0"  # host
        assert args[1] == 9999  # port
        assert args[2] == "envadmin"
        assert args[3] == "envpass"
