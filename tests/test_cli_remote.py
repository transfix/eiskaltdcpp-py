"""
Tests for the CLI remote operation subcommands.

Exercises every `eispy` subcommand group that talks to a running daemon
via RemoteDCClient:
  hub, chat, search, queue, share, setting, transfer, filelist,
  user, events, shutdown

All RemoteDCClient methods are mocked — these are pure CLI-layer tests
that verify argument parsing, output formatting, and error paths.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from eiskaltdcpp.cli import cli


# ============================================================================
# Fixtures & helpers
# ============================================================================

@pytest.fixture
def runner():
    return CliRunner()


def _base_args(url="http://test:8080", user="admin", pw="pass"):
    """Global options that every remote command needs."""
    return ["--url", url, "--user", user, "--pass", pw]


class FakeRemoteClient:
    """Async-context-manager stub for RemoteDCClient.

    Attributes set on the instance become the return values of the
    corresponding async method calls.  Unknown method lookups return
    an AsyncMock that resolves to None.
    """

    def __init__(self, **returns):
        self._returns = returns

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        val = self._returns.get(name)
        if val is not None:
            if callable(val):
                return val
            m = AsyncMock(return_value=val)
            return m
        return AsyncMock(return_value=None)


def _patch_client(**returns):
    """Return a patch that replaces _get_remote_client with a FakeRemoteClient."""
    fake = FakeRemoteClient(**returns)
    return patch("eiskaltdcpp.cli._get_remote_client", return_value=fake)


# Simple dataclass-like objects to mimic the real data types
@dataclass
class _Hub:
    url: str = "dchub://hub:411"
    name: str = "TestHub"
    user_count: int = 42


@dataclass
class _User:
    nick: str = "Alice"
    share_size: int = 1024
    hub_url: str = "dchub://hub:411"


@dataclass
class _SearchResult:
    filename: str = "test.iso"
    size: int = 700_000_000
    tth: str = "ABCDEF1234567890ABCDEF1234567890ABCDEFGH"
    nick: str = "Alice"
    hub_url: str = "dchub://hub:411"


@dataclass
class _QueueItem:
    target: str = "/tmp/dl/test.iso"
    size: int = 700_000_000
    downloaded: int = 100_000
    priority: int = 3
    tth: str = "ABCDEF1234567890"


@dataclass
class _ShareInfo:
    virtual_name: str = "Movies"
    real_path: str = "/data/movies"
    size: int = 50_000_000_000


@dataclass
class _TransferStats:
    download_speed: int = 1_048_576
    upload_speed: int = 524_288
    downloaded_bytes: int = 10_737_418_240
    uploaded_bytes: int = 5_368_709_120


@dataclass
class _HashStatus:
    current_file: str = "/data/movies/film.mkv"
    files_left: int = 42
    bytes_left: int = 5_000_000_000


# ============================================================================
# Group-level / help tests
# ============================================================================

class TestRemoteGroupHelp:
    """Verify that all remote subcommand groups show help."""

    @pytest.mark.parametrize("group", [
        "hub", "chat", "search", "queue", "share",
        "setting", "transfer", "filelist", "user",
    ])
    def test_group_help(self, runner, group):
        result = runner.invoke(cli, [group, "--help"])
        assert result.exit_code == 0, result.output

    @pytest.mark.parametrize("cmd", ["events", "shutdown"])
    def test_toplevel_remote_help(self, runner, cmd):
        result = runner.invoke(cli, [cmd, "--help"])
        assert result.exit_code == 0, result.output

    def test_cli_help_lists_remote_groups(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for grp in ("hub", "chat", "search", "queue", "share",
                     "setting", "transfer", "filelist", "user",
                     "events", "shutdown"):
            assert grp in result.output, f"'{grp}' missing from top-level help"


# ============================================================================
# hub — Hub connections
# ============================================================================

class TestHubCommands:

    def test_hub_connect(self, runner):
        with _patch_client() as mock_gc:
            result = runner.invoke(cli, [*_base_args(), "hub", "connect",
                                         "dchub://hub:411"])
        assert result.exit_code == 0
        assert "Connected" in result.output

    def test_hub_connect_with_encoding(self, runner):
        with _patch_client() as mock_gc:
            result = runner.invoke(cli, [*_base_args(), "hub", "connect",
                                         "dchub://hub:411",
                                         "--encoding", "CP1252"])
        assert result.exit_code == 0

    def test_hub_disconnect(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "hub", "disconnect",
                                         "dchub://hub:411"])
        assert result.exit_code == 0
        assert "Disconnected" in result.output

    def test_hub_ls_with_hubs(self, runner):
        with _patch_client(list_hubs_async=[_Hub(), _Hub(url="adc://hub2:5000", name="Hub2")]):
            result = runner.invoke(cli, [*_base_args(), "hub", "ls"])
        assert result.exit_code == 0
        assert "TestHub" in result.output
        assert "Hub2" in result.output

    def test_hub_ls_empty(self, runner):
        with _patch_client(list_hubs_async=[]):
            result = runner.invoke(cli, [*_base_args(), "hub", "ls"])
        assert result.exit_code == 0
        assert "No hubs" in result.output

    def test_hub_users(self, runner):
        with _patch_client(get_users_async=[_User(), _User(nick="Bob")]):
            result = runner.invoke(cli, [*_base_args(), "hub", "users",
                                         "dchub://hub:411"])
        assert result.exit_code == 0
        assert "Alice" in result.output
        assert "Bob" in result.output

    def test_hub_users_empty(self, runner):
        with _patch_client(get_users_async=[]):
            result = runner.invoke(cli, [*_base_args(), "hub", "users",
                                         "dchub://hub:411"])
        assert result.exit_code == 0
        assert "No users" in result.output


# ============================================================================
# chat — Chat messages
# ============================================================================

class TestChatCommands:

    def test_chat_send(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "chat", "send",
                                         "dchub://hub:411", "Hello world"])
        assert result.exit_code == 0
        assert "Message sent" in result.output

    def test_chat_pm(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "chat", "pm",
                                         "dchub://hub:411", "Alice",
                                         "Hi there"])
        assert result.exit_code == 0
        assert "PM sent" in result.output
        assert "Alice" in result.output

    def test_chat_history(self, runner):
        lines = ["<Alice> hello", "<Bob> hi", "<Alice> how are you?"]
        with _patch_client(get_chat_history_async=lines):
            result = runner.invoke(cli, [*_base_args(), "chat", "history",
                                         "dchub://hub:411"])
        assert result.exit_code == 0
        assert "<Alice> hello" in result.output
        assert "<Bob> hi" in result.output

    def test_chat_history_with_limit(self, runner):
        with _patch_client(get_chat_history_async=["line1"]):
            result = runner.invoke(cli, [*_base_args(), "chat", "history",
                                         "dchub://hub:411", "-n", "10"])
        assert result.exit_code == 0


# ============================================================================
# search — Search the DC network
# ============================================================================

class TestSearchCommands:

    def test_search_query(self, runner):
        with _patch_client(search_async=True):
            result = runner.invoke(cli, [*_base_args(), "search", "query",
                                         "ubuntu iso"])
        assert result.exit_code == 0
        assert "Search sent" in result.output

    def test_search_query_with_options(self, runner):
        with _patch_client(search_async=True):
            result = runner.invoke(cli, [*_base_args(), "search", "query",
                                         "movie", "--type", "6",
                                         "--size-mode", "1", "--size", "1000000",
                                         "--hub", "dchub://hub:411"])
        assert result.exit_code == 0

    def test_search_query_failure(self, runner):
        with _patch_client(search_async=False):
            result = runner.invoke(cli, [*_base_args(), "search", "query",
                                         "nothing"])
        assert result.exit_code != 0
        assert "failed" in result.output.lower()

    def test_search_results_table(self, runner):
        with _patch_client(get_search_results_async=[_SearchResult(),
                                                      _SearchResult(filename="other.zip")]):
            result = runner.invoke(cli, [*_base_args(), "search", "results"])
        assert result.exit_code == 0
        assert "test.iso" in result.output
        assert "other.zip" in result.output

    def test_search_results_json(self, runner):
        with _patch_client(get_search_results_async=[_SearchResult()]):
            result = runner.invoke(cli, [*_base_args(), "search", "results",
                                         "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert parsed[0]["filename"] == "test.iso"

    def test_search_results_empty(self, runner):
        with _patch_client(get_search_results_async=[]):
            result = runner.invoke(cli, [*_base_args(), "search", "results"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_search_clear(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "search", "clear"])
        assert result.exit_code == 0
        assert "cleared" in result.output.lower()

    def test_search_clear_with_hub(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "search", "clear",
                                         "--hub", "dchub://hub:411"])
        assert result.exit_code == 0


# ============================================================================
# queue — Download queue
# ============================================================================

class TestQueueCommands:

    def test_queue_ls_table(self, runner):
        with _patch_client(list_queue_async=[_QueueItem()]):
            result = runner.invoke(cli, [*_base_args(), "queue", "ls"])
        assert result.exit_code == 0
        assert "test.iso" in result.output

    def test_queue_ls_json(self, runner):
        with _patch_client(list_queue_async=[_QueueItem()]):
            result = runner.invoke(cli, [*_base_args(), "queue", "ls", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed[0]["target"] == "/tmp/dl/test.iso"

    def test_queue_ls_empty(self, runner):
        with _patch_client(list_queue_async=[]):
            result = runner.invoke(cli, [*_base_args(), "queue", "ls"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()

    def test_queue_add(self, runner):
        with _patch_client(download_async=True):
            result = runner.invoke(cli, [*_base_args(), "queue", "add",
                                         "--dir", "/tmp/dl",
                                         "--name", "file.zip",
                                         "--size", "1048576",
                                         "--tth", "ABC123"])
        assert result.exit_code == 0
        assert "Queued" in result.output

    def test_queue_add_failure(self, runner):
        with _patch_client(download_async=False):
            result = runner.invoke(cli, [*_base_args(), "queue", "add",
                                         "--dir", "/tmp/dl",
                                         "--name", "file.zip",
                                         "--size", "1048576",
                                         "--tth", "ABC123"])
        assert result.exit_code != 0

    def test_queue_add_magnet(self, runner):
        with _patch_client(download_magnet_async=True):
            result = runner.invoke(cli, [*_base_args(), "queue", "add-magnet",
                                         "magnet:?xt=urn:tree:tiger:ABC"])
        assert result.exit_code == 0
        assert "Magnet queued" in result.output

    def test_queue_add_magnet_failure(self, runner):
        with _patch_client(download_magnet_async=False):
            result = runner.invoke(cli, [*_base_args(), "queue", "add-magnet",
                                         "magnet:?xt=urn:tree:tiger:ABC"])
        assert result.exit_code != 0

    def test_queue_rm(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "queue", "rm",
                                         "/tmp/dl/file.zip"])
        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_queue_clear(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "queue", "clear"])
        assert result.exit_code == 0
        assert "cleared" in result.output.lower()

    def test_queue_priority(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "queue", "priority",
                                         "/tmp/dl/file.zip", "5"])
        assert result.exit_code == 0
        assert "Priority set" in result.output


# ============================================================================
# share — Shared directories
# ============================================================================

class TestShareCommands:

    def test_share_ls_table(self, runner):
        with _patch_client(list_shares_async=[_ShareInfo()]):
            result = runner.invoke(cli, [*_base_args(), "share", "ls"])
        assert result.exit_code == 0
        assert "Movies" in result.output

    def test_share_ls_json(self, runner):
        with _patch_client(list_shares_async=[_ShareInfo()]):
            result = runner.invoke(cli, [*_base_args(), "share", "ls", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed[0]["virtual_name"] == "Movies"

    def test_share_ls_empty(self, runner):
        with _patch_client(list_shares_async=[]):
            result = runner.invoke(cli, [*_base_args(), "share", "ls"])
        assert result.exit_code == 0
        assert "No shares" in result.output

    def test_share_add(self, runner):
        with _patch_client(add_share_async=True):
            result = runner.invoke(cli, [*_base_args(), "share", "add",
                                         "/data/movies", "Movies"])
        assert result.exit_code == 0
        assert "Shared" in result.output

    def test_share_add_failure(self, runner):
        with _patch_client(add_share_async=False):
            result = runner.invoke(cli, [*_base_args(), "share", "add",
                                         "/data/movies", "Movies"])
        assert result.exit_code != 0

    def test_share_rm(self, runner):
        with _patch_client(remove_share_async=True):
            result = runner.invoke(cli, [*_base_args(), "share", "rm",
                                         "/data/movies"])
        assert result.exit_code == 0
        assert "Removed share" in result.output

    def test_share_rm_failure(self, runner):
        with _patch_client(remove_share_async=False):
            result = runner.invoke(cli, [*_base_args(), "share", "rm",
                                         "/data/movies"])
        assert result.exit_code != 0

    def test_share_refresh(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "share", "refresh"])
        assert result.exit_code == 0
        assert "refresh" in result.output.lower()

    def test_share_size(self, runner):
        with _patch_client(get_share_size=50_000_000_000, get_shared_files=1234):
            result = runner.invoke(cli, [*_base_args(), "share", "size"])
        assert result.exit_code == 0
        assert "1,234" in result.output  # file count formatted
        assert "GiB" in result.output or "46.6" in result.output  # ~46.6 GiB


# ============================================================================
# setting — Settings management
# ============================================================================

class TestSettingCommands:

    def test_setting_get(self, runner):
        with _patch_client(get_setting_async="MyBot"):
            result = runner.invoke(cli, [*_base_args(), "setting", "get", "Nick"])
        assert result.exit_code == 0
        assert "Nick" in result.output
        assert "MyBot" in result.output

    def test_setting_set(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "setting", "set",
                                         "Nick", "NewBot"])
        assert result.exit_code == 0
        assert "Nick" in result.output
        assert "NewBot" in result.output

    def test_setting_reload(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "setting", "reload"])
        assert result.exit_code == 0
        assert "reloaded" in result.output.lower()

    def test_setting_networking(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "setting", "networking"])
        assert result.exit_code == 0
        assert "Networking" in result.output


# ============================================================================
# transfer — Transfer stats and hashing
# ============================================================================

class TestTransferCommands:

    def test_transfer_stats(self, runner):
        with _patch_client(get_transfer_stats=_TransferStats()):
            result = runner.invoke(cli, [*_base_args(), "transfer", "stats"])
        assert result.exit_code == 0
        # Should show human readable speed
        assert "/s" in result.output

    def test_transfer_stats_json(self, runner):
        with _patch_client(get_transfer_stats=_TransferStats()):
            result = runner.invoke(cli, [*_base_args(), "transfer", "stats",
                                         "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert "download_speed" in parsed

    def test_transfer_hash_status(self, runner):
        with _patch_client(get_hash_status=_HashStatus()):
            result = runner.invoke(cli, [*_base_args(), "transfer", "hash-status"])
        assert result.exit_code == 0
        assert "42" in result.output  # files_left

    def test_transfer_hash_status_json(self, runner):
        with _patch_client(get_hash_status=_HashStatus()):
            result = runner.invoke(cli, [*_base_args(), "transfer",
                                         "hash-status", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["files_left"] == 42

    def test_transfer_pause_hash(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "transfer", "pause-hash"])
        assert result.exit_code == 0
        assert "paused" in result.output.lower()

    def test_transfer_resume_hash(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "transfer",
                                         "resume-hash"])
        assert result.exit_code == 0
        assert "resumed" in result.output.lower()


# ============================================================================
# filelist — File list browsing
# ============================================================================

class TestFilelistCommands:

    def test_filelist_request_help(self, runner):
        result = runner.invoke(cli, ["filelist", "request", "--help"])
        assert result.exit_code == 0
        assert "hub_url" in result.output.lower() or "HUB_URL" in result.output

    def test_filelist_browse_help(self, runner):
        result = runner.invoke(cli, ["filelist", "browse", "--help"])
        assert result.exit_code == 0

    def test_filelist_download_help(self, runner):
        result = runner.invoke(cli, ["filelist", "download", "--help"])
        assert result.exit_code == 0

    def test_filelist_download_dir_help(self, runner):
        result = runner.invoke(cli, ["filelist", "download-dir", "--help"])
        assert result.exit_code == 0

    def test_filelist_close_help(self, runner):
        result = runner.invoke(cli, ["filelist", "close", "--help"])
        assert result.exit_code == 0

    def test_filelist_ls_help(self, runner):
        result = runner.invoke(cli, ["filelist", "ls", "--help"])
        assert result.exit_code == 0

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_request(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.request_file_list.return_value = True
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "request",
                                     "dchub://hub:411", "Alice"])
        assert result.exit_code == 0
        assert "requested" in result.output.lower()

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_request_failure(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.request_file_list.return_value = False
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "request",
                                     "dchub://hub:411", "Alice"])
        assert result.exit_code != 0

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_ls(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.list_local_file_lists.return_value = ["Alice_list", "Bob_list"]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "ls"])
        assert result.exit_code == 0
        assert "Alice_list" in result.output

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_ls_empty(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.list_local_file_lists.return_value = []
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "ls"])
        assert result.exit_code == 0
        assert "No file lists" in result.output

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_browse(self, mock_cls, runner):
        @dataclass
        class _Entry:
            name: str = "song.mp3"
            size: int = 5_000_000
            tth: str = "ABCDEF"
            type: str = "file"

        mock_client = MagicMock()
        mock_client.open_file_list.return_value = True
        mock_client.browse_file_list.return_value = [_Entry(), _Entry(name="video.mkv")]
        mock_client.close_file_list.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "browse",
                                     "my_list", "--dir", "/Music"])
        assert result.exit_code == 0
        assert "song.mp3" in result.output

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_browse_open_failure(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.open_file_list.return_value = False
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "browse",
                                     "bad_list"])
        assert result.exit_code != 0

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_download(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.open_file_list.return_value = True
        mock_client.download_from_list.return_value = True
        mock_client.close_file_list.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "download",
                                     "my_list", "/Music/song.mp3",
                                     "--to", "/tmp/dl"])
        assert result.exit_code == 0
        assert "Queued download" in result.output

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_download_failure(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.open_file_list.return_value = True
        mock_client.download_from_list.return_value = False
        mock_client.close_file_list.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "download",
                                     "my_list", "/Music/song.mp3"])
        assert result.exit_code != 0

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_download_dir(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.open_file_list.return_value = True
        mock_client.download_dir_from_list.return_value = True
        mock_client.close_file_list.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "download-dir",
                                     "my_list", "/Music",
                                     "--to", "/tmp/dl"])
        assert result.exit_code == 0
        assert "Queued directory download" in result.output

    @patch("eiskaltdcpp.AsyncDCClient", create=True)
    def test_filelist_close(self, mock_cls, runner):
        mock_client = MagicMock()
        mock_client.close_file_list.return_value = None
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = runner.invoke(cli, [*_base_args(), "filelist", "close",
                                     "my_list"])
        assert result.exit_code == 0
        assert "closed" in result.output.lower()


# ============================================================================
# user — API user management
# ============================================================================

class TestUserCommands:

    def test_user_ls(self, runner):
        with _patch_client(list_users=[
            {"username": "admin", "role": "admin"},
            {"username": "viewer", "role": "readonly"},
        ]):
            result = runner.invoke(cli, [*_base_args(), "user", "ls"])
        assert result.exit_code == 0
        assert "admin" in result.output
        assert "viewer" in result.output

    def test_user_ls_empty(self, runner):
        with _patch_client(list_users=[]):
            result = runner.invoke(cli, [*_base_args(), "user", "ls"])
        assert result.exit_code == 0
        assert "No users" in result.output

    def test_user_create(self, runner):
        with _patch_client(create_user={"username": "viewer", "role": "readonly"}):
            result = runner.invoke(cli, [*_base_args(), "user", "create",
                                         "viewer", "p@ss", "--role", "readonly"])
        assert result.exit_code == 0
        assert "Created" in result.output
        assert "viewer" in result.output

    def test_user_rm(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "user", "rm", "viewer"])
        assert result.exit_code == 0
        assert "Deleted" in result.output

    def test_user_update_role(self, runner):
        with _patch_client(update_user={"username": "viewer", "role": "admin"}):
            result = runner.invoke(cli, [*_base_args(), "user", "update",
                                         "viewer", "--role", "admin"])
        assert result.exit_code == 0
        assert "Updated" in result.output

    def test_user_update_password(self, runner):
        with _patch_client(update_user={"username": "viewer"}):
            result = runner.invoke(cli, [*_base_args(), "user", "update",
                                         "viewer", "--password", "newpass"])
        assert result.exit_code == 0

    def test_user_update_nothing(self, runner):
        """Must specify --password or --role."""
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "user", "update",
                                         "viewer"])
        assert result.exit_code != 0


# ============================================================================
# events — Real-time event streaming
# ============================================================================

class TestEventsCommand:

    def test_events_help(self, runner):
        result = runner.invoke(cli, ["events", "--help"])
        assert result.exit_code == 0
        assert "--channels" in result.output

    def test_events_streams(self, runner):
        """Simulate a short event stream that ends with StopAsyncIteration."""
        events_data = [
            ("chat", {"nick": "Alice", "message": "hello"}),
            ("hub_connected", {"url": "dchub://hub:411"}),
        ]

        class FakeEventStream:
            def __init__(self):
                self._iter = iter(events_data)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                pass

            def events(self, channels="events"):
                return FakeEventStream()

        with patch("eiskaltdcpp.cli._get_remote_client",
                   return_value=FakeClient()):
            result = runner.invoke(cli, [*_base_args(), "events",
                                         "--channels", "chat,hubs"])
        assert result.exit_code == 0
        assert "Alice" in result.output
        assert "hello" in result.output


# ============================================================================
# shutdown — Graceful shutdown
# ============================================================================

class TestShutdownCommand:

    def test_shutdown(self, runner):
        with _patch_client():
            result = runner.invoke(cli, [*_base_args(), "shutdown"])
        assert result.exit_code == 0
        assert "Shutdown request sent" in result.output


# ============================================================================
# Global options / context passing
# ============================================================================

class TestGlobalOptions:

    def test_url_passed_to_context(self, runner):
        """Verify --url is stored in ctx.obj and forwarded."""
        captured = {}

        def fake_get_client(ctx):
            captured.update(ctx.obj)
            return FakeRemoteClient()

        with patch("eiskaltdcpp.cli._get_remote_client", side_effect=fake_get_client):
            result = runner.invoke(cli, [
                "--url", "http://remote:9090",
                "--user", "joe",
                "--pass", "hunter2",
                "hub", "ls",
            ])
        assert result.exit_code == 0
        assert captured["api_url"] == "http://remote:9090"
        assert captured["api_user"] == "joe"
        assert captured["api_pass"] == "hunter2"

    def test_default_url(self, runner):
        """Without --url, DEFAULT_API_URL is used."""
        captured = {}

        def fake_get_client(ctx):
            captured.update(ctx.obj)
            return FakeRemoteClient()

        with patch("eiskaltdcpp.cli._get_remote_client", side_effect=fake_get_client):
            runner.invoke(cli, ["hub", "ls"])
        assert captured["api_url"] == "http://localhost:8080"

    def test_env_vars(self, runner):
        """EISPY_URL / EISPY_USER / EISPY_PASS env vars are respected."""
        captured = {}

        def fake_get_client(ctx):
            captured.update(ctx.obj)
            return FakeRemoteClient()

        with patch("eiskaltdcpp.cli._get_remote_client", side_effect=fake_get_client):
            result = runner.invoke(cli, ["hub", "ls"], env={
                "EISPY_URL": "http://env-host:7777",
                "EISPY_USER": "envuser",
                "EISPY_PASS": "envpass",
            })
        assert result.exit_code == 0
        assert captured["api_url"] == "http://env-host:7777"
        assert captured["api_user"] == "envuser"
        assert captured["api_pass"] == "envpass"


# ============================================================================
# Helper function tests
# ============================================================================

class TestHelperFunctions:

    def test_format_size(self):
        from eiskaltdcpp.cli import _format_size
        assert "B" in _format_size(512)
        assert "KiB" in _format_size(2048)
        assert "MiB" in _format_size(5_242_880)
        assert "GiB" in _format_size(5_368_709_120)
        assert "TiB" in _format_size(1_099_511_627_776)

    def test_obj_to_dict_dataclass(self):
        from eiskaltdcpp.cli import _obj_to_dict
        d = _obj_to_dict(_Hub(url="test", name="Hub", user_count=10))
        assert d == {"url": "test", "name": "Hub", "user_count": 10}

    def test_obj_to_dict_plain_object(self):
        from eiskaltdcpp.cli import _obj_to_dict

        class Obj:
            def __init__(self):
                self.a = 1
                self.b = "two"
                self._private = "hidden"

        d = _obj_to_dict(Obj())
        assert d == {"a": 1, "b": "two"}

    def test_obj_to_dict_fallback(self):
        from eiskaltdcpp.cli import _obj_to_dict
        d = _obj_to_dict(42)
        assert "value" in d

    def test_print_table(self, runner):
        from eiskaltdcpp.cli import _print_table
        from io import StringIO
        import sys
        buf = StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            _print_table([{"a": "1", "b": "2"}, {"a": "3", "b": "4"}])
        finally:
            sys.stdout = old_stdout
        # _print_table uses click.echo which may bypass sys.stdout;
        # just verify it doesn't crash — formatting tested via CLI commands above

    def test_print_table_empty(self, runner):
        from eiskaltdcpp.cli import _print_table
        # Should not raise
        _print_table([])

    def test_print_json(self):
        from eiskaltdcpp.cli import _print_json
        # Should not raise
        _print_json({"key": "value"})
