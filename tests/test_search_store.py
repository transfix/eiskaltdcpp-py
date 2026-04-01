"""Tests for saved search result store (search_store.py) and CLI integration."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from eiskaltdcpp.search_store import (
    _get_searches_dir,
    _safe_filename,
    list_saved_searches,
    load_search,
    purge_all_searches,
    purge_search,
    save_search,
)
from eiskaltdcpp.cli import cli


@pytest.fixture
def search_dir(tmp_path, monkeypatch):
    """Point search storage at a temporary directory."""
    d = tmp_path / "searches"
    monkeypatch.setenv("EISPY_SEARCHES_DIR", str(d))
    return d


@pytest.fixture
def runner():
    return CliRunner()


# Sample results for testing
SAMPLE_RESULTS = [
    {
        "file": "ubuntu-22.04-desktop-amd64.iso",
        "size": 3654957056,
        "tth": "ABC123",
        "nick": "UserA",
        "hubUrl": "nmdcs://hub:411",
        "hubName": "TestHub",
        "freeSlots": 3,
        "totalSlots": 5,
        "isDirectory": False,
    },
    {
        "file": "ubuntu-22.04-server-amd64.iso",
        "size": 1474560000,
        "tth": "DEF456",
        "nick": "UserB",
        "hubUrl": "nmdcs://hub:411",
        "hubName": "TestHub",
        "freeSlots": 1,
        "totalSlots": 4,
        "isDirectory": False,
    },
]


# ============================================================================
# search_store module — core logic
# ============================================================================

class TestSafeFilename:
    def test_simple_name(self):
        assert _safe_filename("ubuntu") == "ubuntu"

    def test_spaces_replaced(self):
        assert _safe_filename("my search") == "my_search"

    def test_special_chars_replaced(self):
        assert _safe_filename("a/b\\c:d") == "a_b_c_d"

    def test_dot_only_name(self):
        assert _safe_filename("...") == "search"

    def test_empty_string(self):
        assert _safe_filename("") == "search"

    def test_preserves_dashes_underscores(self):
        assert _safe_filename("my-search_v2") == "my-search_v2"


class TestSaveLoad:
    def test_save_and_load(self, search_dir):
        save_search("ubuntu", "ubuntu iso", SAMPLE_RESULTS)
        data = load_search("ubuntu")
        assert data is not None
        assert data["name"] == "ubuntu"
        assert data["query"] == "ubuntu iso"
        assert data["count"] == 2
        assert len(data["results"]) == 2
        assert data["results"][0]["file"] == "ubuntu-22.04-desktop-amd64.iso"

    def test_save_with_params(self, search_dir):
        save_search(
            "videos", "movie.mkv", SAMPLE_RESULTS,
            file_type=6, size_mode=1, size=5000000000,
            hub_url="nmdcs://hub:411",
        )
        data = load_search("videos")
        assert data["file_type"] == 6
        assert data["size_mode"] == 1
        assert data["size"] == 5000000000
        assert data["hub_url"] == "nmdcs://hub:411"

    def test_save_creates_directory(self, search_dir):
        assert not search_dir.exists()
        save_search("test", "test query", [])
        assert search_dir.exists()

    def test_save_overwrites(self, search_dir):
        save_search("test", "query1", [{"file": "a"}])
        save_search("test", "query2", [{"file": "b"}])
        data = load_search("test")
        assert data["query"] == "query2"
        assert data["results"] == [{"file": "b"}]

    def test_load_missing(self, search_dir):
        assert load_search("nonexistent") is None

    def test_load_corrupt_file(self, search_dir):
        search_dir.mkdir(parents=True)
        (search_dir / "bad.json").write_text("not json")
        assert load_search("bad") is None

    def test_has_timestamp(self, search_dir):
        save_search("test", "q", [])
        data = load_search("test")
        assert "timestamp" in data
        assert "timestamp_iso" in data
        # Timestamp should be recent
        assert abs(data["timestamp"] - time.time()) < 5

    def test_empty_results(self, search_dir):
        save_search("empty", "nothing matches", [])
        data = load_search("empty")
        assert data["count"] == 0
        assert data["results"] == []


class TestListSavedSearches:
    def test_empty(self, search_dir):
        assert list_saved_searches() == []

    def test_lists_multiple(self, search_dir):
        save_search("ubuntu", "ubuntu iso", SAMPLE_RESULTS)
        save_search("fedora", "fedora iso", [SAMPLE_RESULTS[0]])
        entries = list_saved_searches()
        assert len(entries) == 2
        names = [e["name"] for e in entries]
        assert "ubuntu" in names
        assert "fedora" in names

    def test_metadata_only(self, search_dir):
        save_search("test", "query", SAMPLE_RESULTS)
        entries = list_saved_searches()
        assert len(entries) == 1
        entry = entries[0]
        assert "results" not in entry  # metadata only
        assert entry["count"] == 2
        assert entry["query"] == "query"


class TestPurge:
    def test_purge_existing(self, search_dir):
        save_search("test", "q", [])
        assert purge_search("test") is True
        assert load_search("test") is None

    def test_purge_nonexistent(self, search_dir):
        assert purge_search("nope") is False

    def test_purge_preserves_others(self, search_dir):
        save_search("a", "qa", [])
        save_search("b", "qb", [])
        purge_search("a")
        assert load_search("a") is None
        assert load_search("b") is not None

    def test_purge_all(self, search_dir):
        save_search("a", "qa", [])
        save_search("b", "qb", [])
        save_search("c", "qc", [])
        count = purge_all_searches()
        assert count == 3
        assert list_saved_searches() == []

    def test_purge_all_empty(self, search_dir):
        assert purge_all_searches() == 0


class TestGetSearchesDir:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("EISPY_SEARCHES_DIR", "/custom/searches")
        assert _get_searches_dir() == Path("/custom/searches")

    def test_xdg_config_home(self, monkeypatch):
        monkeypatch.delenv("EISPY_SEARCHES_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg")
        assert _get_searches_dir() == Path("/xdg/eispy/searches")

    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("EISPY_SEARCHES_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = _get_searches_dir()
        assert result == Path.home() / ".config" / "eispy" / "searches"


# ============================================================================
# CLI integration — eispy search saved/show/purge
# ============================================================================

class TestCLISearchSaved:
    def test_saved_empty(self, search_dir, runner):
        result = runner.invoke(cli, ["search", "saved"])
        assert result.exit_code == 0
        assert "no saved" in result.output.lower()

    def test_saved_lists_entries(self, search_dir, runner):
        save_search("ubuntu", "ubuntu iso", SAMPLE_RESULTS)
        save_search("fedora", "fedora iso", [SAMPLE_RESULTS[0]])
        result = runner.invoke(cli, ["search", "saved"])
        assert result.exit_code == 0
        assert "ubuntu" in result.output
        assert "fedora" in result.output


class TestCLISearchShow:
    def test_show_existing(self, search_dir, runner):
        save_search("ubuntu", "ubuntu iso", SAMPLE_RESULTS)
        result = runner.invoke(cli, ["search", "show", "ubuntu"])
        assert result.exit_code == 0
        assert "ubuntu iso" in result.output
        assert "2 results" in result.output
        assert "ubuntu-22.04-desktop-amd64.iso" in result.output

    def test_show_json(self, search_dir, runner):
        save_search("ubuntu", "ubuntu iso", SAMPLE_RESULTS)
        result = runner.invoke(cli, ["search", "show", "ubuntu", "--json"])
        assert result.exit_code == 0
        # First line is the header, JSON starts after
        lines = result.output.strip().split("\n")
        json_text = "\n".join(lines[1:])
        data = json.loads(json_text)
        assert len(data) == 2

    def test_show_nonexistent(self, search_dir, runner):
        result = runner.invoke(cli, ["search", "show", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_show_empty_results(self, search_dir, runner):
        save_search("empty", "nothing", [])
        result = runner.invoke(cli, ["search", "show", "empty"])
        assert result.exit_code == 0
        assert "0 results" in result.output


class TestCLISearchPurge:
    def test_purge_existing(self, search_dir, runner):
        save_search("ubuntu", "ubuntu iso", SAMPLE_RESULTS)
        result = runner.invoke(cli, ["search", "purge", "ubuntu"])
        assert result.exit_code == 0
        assert "purged" in result.output.lower()
        assert load_search("ubuntu") is None

    def test_purge_nonexistent(self, search_dir, runner):
        result = runner.invoke(cli, ["search", "purge", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_purge_all(self, search_dir, runner):
        save_search("a", "qa", [])
        save_search("b", "qb", [])
        result = runner.invoke(cli, ["search", "purge", "--all"])
        assert result.exit_code == 0
        assert "2" in result.output
        assert list_saved_searches() == []

    def test_purge_no_args(self, search_dir, runner):
        result = runner.invoke(cli, ["search", "purge"])
        assert result.exit_code != 0


class TestCLISearchQuerySave:
    """Test the --save flag on search query."""

    def test_query_save_captures_results(self, search_dir, runner):
        """--save should clear, search, wait, save results."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.search_async.return_value = True
        # Simulate returning results after the wait
        mock_client.get_search_results_async.return_value = [
            type("R", (), d)() for d in SAMPLE_RESULTS
        ]

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, [
                "search", "query", "ubuntu iso",
                "--save", "ubuntu", "--wait", "1",
            ])

        assert result.exit_code == 0
        assert "ubuntu" in result.output
        mock_client.clear_search_results_async.assert_called_once()
        mock_client.search_async.assert_called_once()

        # Verify results were saved
        data = load_search("ubuntu")
        assert data is not None
        assert data["query"] == "ubuntu iso"
        assert data["count"] == 2

    def test_query_without_save(self, search_dir, runner):
        """Without --save, should work as before (fire and forget)."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.search_async.return_value = True

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, ["search", "query", "ubuntu iso"])

        assert result.exit_code == 0
        assert "search sent" in result.output.lower()
        # Should NOT call clear or get_search_results
        mock_client.clear_search_results_async.assert_not_called()
        mock_client.get_search_results_async.assert_not_called()
        # No saved search should exist
        assert list_saved_searches() == []

    def test_query_save_search_fails(self, search_dir, runner):
        """When search fails, --save should still report the error."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.search_async.return_value = False

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, [
                "search", "query", "ubuntu",
                "--save", "test", "--wait", "1",
            ])

        assert result.exit_code != 0
        assert "failed" in result.output.lower()
        assert load_search("test") is None

    def test_query_help_shows_save_options(self, runner):
        result = runner.invoke(cli, ["search", "query", "--help"])
        assert result.exit_code == 0
        assert "--save" in result.output
        assert "--wait" in result.output
        assert "--min-results" in result.output
