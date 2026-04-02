"""Tests for hub alias management (hub_aliases.py) and CLI integration."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from eiskaltdcpp.hub_aliases import (
    _get_hubs_file,
    add_alias,
    list_aliases,
    load_aliases,
    remove_alias,
    resolve,
    reverse_lookup,
    save_aliases,
)
from eiskaltdcpp.cli import cli


@pytest.fixture
def alias_file(tmp_path, monkeypatch):
    """Point alias storage at a temporary file."""
    f = tmp_path / "hubs.json"
    monkeypatch.setenv("EISPY_HUBS_FILE", str(f))
    return f


@pytest.fixture
def runner():
    return CliRunner()


# ============================================================================
# hub_aliases module — core logic
# ============================================================================

class TestLoadSave:
    """load_aliases / save_aliases round-trip."""

    def test_load_missing_file(self, alias_file):
        assert load_aliases() == {}

    def test_save_and_load(self, alias_file):
        data = {"winter": "nmdcs://wintermute:411", "hub2": "dchub://hub2:411"}
        save_aliases(data)
        assert load_aliases() == data

    def test_load_invalid_json(self, alias_file):
        alias_file.write_text("not json", encoding="utf-8")
        assert load_aliases() == {}

    def test_load_non_dict_json(self, alias_file):
        alias_file.write_text('["a", "b"]', encoding="utf-8")
        assert load_aliases() == {}

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        deep = tmp_path / "a" / "b" / "hubs.json"
        monkeypatch.setenv("EISPY_HUBS_FILE", str(deep))
        save_aliases({"x": "dchub://x:1"})
        assert deep.exists()
        assert json.loads(deep.read_text()) == {"x": "dchub://x:1"}


class TestAddRemove:
    """add_alias / remove_alias."""

    def test_add_new(self, alias_file):
        add_alias("winter", "nmdcs://wintermute:411")
        assert load_aliases() == {"winter": "nmdcs://wintermute:411"}

    def test_add_overwrites(self, alias_file):
        add_alias("winter", "nmdcs://old:411")
        add_alias("winter", "nmdcs://new:411")
        assert load_aliases()["winter"] == "nmdcs://new:411"

    def test_add_multiple(self, alias_file):
        add_alias("a", "dchub://a:411")
        add_alias("b", "nmdcs://b:411")
        aliases = load_aliases()
        assert len(aliases) == 2
        assert aliases["a"] == "dchub://a:411"
        assert aliases["b"] == "nmdcs://b:411"

    def test_remove_existing(self, alias_file):
        add_alias("winter", "nmdcs://wintermute:411")
        assert remove_alias("winter") is True
        assert load_aliases() == {}

    def test_remove_nonexistent(self, alias_file):
        assert remove_alias("nope") is False

    def test_remove_preserves_others(self, alias_file):
        add_alias("a", "dchub://a:411")
        add_alias("b", "dchub://b:411")
        remove_alias("a")
        assert load_aliases() == {"b": "dchub://b:411"}


class TestResolve:
    """resolve() — alias lookup vs URL pass-through."""

    def test_url_passthrough_dchub(self, alias_file):
        assert resolve("dchub://hub:411") == "dchub://hub:411"

    def test_url_passthrough_nmdcs(self, alias_file):
        assert resolve("nmdcs://hub:411") == "nmdcs://hub:411"

    def test_url_passthrough_adc(self, alias_file):
        assert resolve("adc://hub:5000") == "adc://hub:5000"

    def test_url_passthrough_adcs(self, alias_file):
        assert resolve("adcs://hub:5001") == "adcs://hub:5001"

    def test_alias_resolve(self, alias_file):
        add_alias("winter", "nmdcs://wintermute:411")
        assert resolve("winter") == "nmdcs://wintermute:411"

    def test_alias_not_found(self, alias_file):
        with pytest.raises(KeyError, match="Unknown hub alias"):
            resolve("nonexistent")

    def test_error_message_lists_known(self, alias_file):
        add_alias("winter", "nmdcs://w:411")
        add_alias("pub", "dchub://p:411")
        with pytest.raises(KeyError, match="pub.*winter|winter.*pub"):
            resolve("missing")


class TestListAliases:
    def test_empty(self, alias_file):
        assert list_aliases() == {}

    def test_returns_all(self, alias_file):
        add_alias("a", "dchub://a:411")
        add_alias("b", "nmdcs://b:411")
        assert list_aliases() == {"a": "dchub://a:411", "b": "nmdcs://b:411"}


class TestReverseLookup:
    def test_found(self, alias_file):
        add_alias("winter", "nmdcs://wintermute.sublevels.net:411")
        assert reverse_lookup("nmdcs://wintermute.sublevels.net:411") == "winter"

    def test_not_found(self, alias_file):
        assert reverse_lookup("dchub://unknown:411") is None

    def test_empty_file(self, alias_file):
        assert reverse_lookup("dchub://any:411") is None

    def test_first_match_wins(self, alias_file):
        """When multiple aliases map to the same URL, any one is acceptable."""
        add_alias("alpha", "dchub://same:411")
        add_alias("beta", "dchub://same:411")
        result = reverse_lookup("dchub://same:411")
        assert result in ("alpha", "beta")


class TestGetHubsFile:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("EISPY_HUBS_FILE", "/custom/path.json")
        assert _get_hubs_file() == Path("/custom/path.json")

    def test_xdg_config_home(self, monkeypatch):
        monkeypatch.delenv("EISPY_HUBS_FILE", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg")
        assert _get_hubs_file() == Path("/xdg/eispy/hubs.json")

    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("EISPY_HUBS_FILE", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = _get_hubs_file()
        assert result == Path.home() / ".config" / "eispy" / "hubs.json"


# ============================================================================
# CLI integration — eispy hub alias subcommands
# ============================================================================

class TestCLIHubAlias:
    """Test eispy hub alias add/rm/ls via Click CliRunner."""

    def test_alias_add(self, alias_file, runner):
        result = runner.invoke(cli, [
            "hub", "alias", "add", "winter", "nmdcs://wintermute:411",
        ])
        assert result.exit_code == 0
        assert "winter" in result.output
        assert "nmdcs://wintermute:411" in result.output
        assert load_aliases()["winter"] == "nmdcs://wintermute:411"

    def test_alias_add_no_scheme_rejected(self, alias_file, runner):
        result = runner.invoke(cli, [
            "hub", "alias", "add", "bad", "wintermute:411",
        ])
        assert result.exit_code != 0
        assert "scheme" in result.output.lower() or "scheme" in (result.exception and str(result.exception) or "").lower()

    def test_alias_ls_empty(self, alias_file, runner):
        result = runner.invoke(cli, ["hub", "alias", "ls"])
        assert result.exit_code == 0
        assert "no hub aliases" in result.output.lower()

    def test_alias_ls_shows_entries(self, alias_file, runner):
        add_alias("alpha", "dchub://alpha:411")
        add_alias("beta", "nmdcs://beta:411")
        result = runner.invoke(cli, ["hub", "alias", "ls"])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" in result.output
        assert "dchub://alpha:411" in result.output
        assert "nmdcs://beta:411" in result.output

    def test_alias_rm(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        result = runner.invoke(cli, ["hub", "alias", "rm", "winter"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()
        assert load_aliases() == {}

    def test_alias_rm_nonexistent(self, alias_file, runner):
        result = runner.invoke(cli, ["hub", "alias", "rm", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_alias_help(self, alias_file, runner):
        result = runner.invoke(cli, ["hub", "alias", "--help"])
        assert result.exit_code == 0
        assert "alias" in result.output.lower()


# ============================================================================
# CLI integration — alias resolution in hub commands
# ============================================================================

class TestCLIAliasResolution:
    """Alias resolution is applied to hub URL arguments/options."""

    def test_hub_connect_resolves_alias(self, alias_file, runner):
        """hub connect should resolve an alias to the full URL."""
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, ["hub", "connect", "winter"])

        assert result.exit_code == 0, (
            f"exit_code={result.exit_code}, output={result.output!r}, "
            f"exception={result.exception!r}"
        )
        mock_client.connect.assert_called_once_with(
            "nmdcs://wintermute:411", "",
        )

    def test_hub_connect_passthrough_url(self, alias_file, runner):
        """hub connect with a full URL should not attempt alias lookup."""
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, [
                "hub", "connect", "nmdcs://direct:411",
            ])

        assert result.exit_code == 0, (
            f"exit_code={result.exit_code}, output={result.output!r}, "
            f"exception={result.exception!r}"
        )
        mock_client.connect.assert_called_once_with("nmdcs://direct:411", "")

    def test_hub_connect_unknown_alias_fails(self, alias_file, runner):
        """hub connect with an unknown alias should fail with a clear error."""
        result = runner.invoke(cli, ["hub", "connect", "unknown"])
        assert result.exit_code != 0
        assert "unknown" in result.output.lower() or "unknown" in str(result.exception or "").lower()

    def test_hub_disconnect_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, ["hub", "disconnect", "winter"])

        assert result.exit_code == 0
        mock_client.disconnect.assert_called_once_with("nmdcs://wintermute:411")

    def test_chat_send_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, [
                "chat", "send", "winter", "Hello!",
            ])

        assert result.exit_code == 0
        mock_client.send_message_async.assert_called_once_with(
            "nmdcs://wintermute:411", "Hello!",
        )

    def test_search_hub_option_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.search_async.return_value = True

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, [
                "search", "query", "ubuntu", "--hub", "winter",
            ])

        assert result.exit_code == 0
        call_kwargs = mock_client.search_async.call_args
        # hub_url should be resolved
        assert call_kwargs[1].get("hub_url") == "nmdcs://wintermute:411" or \
               call_kwargs[0][-1] == "nmdcs://wintermute:411"

    def test_filelist_request_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        instance = AsyncMock()
        instance.request_file_list.return_value = True
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)

        with patch("eiskaltdcpp.AsyncDCClient", return_value=instance):
            result = runner.invoke(cli, [
                "filelist", "request", "winter", "SomeUser",
            ])

        assert result.exit_code == 0
        instance.request_file_list.assert_called_once_with(
            "nmdcs://wintermute:411", "SomeUser", match_queue=False,
        )

    def test_hub_users_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get_users_async.return_value = []

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, ["hub", "users", "winter"])

        assert result.exit_code == 0
        mock_client.get_users_async.assert_called_once_with(
            "nmdcs://wintermute:411",
        )

    def test_chat_pm_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, [
                "chat", "pm", "winter", "SomeUser", "Hello!",
            ])

        assert result.exit_code == 0
        mock_client.send_pm_async.assert_called_once_with(
            "nmdcs://wintermute:411", "SomeUser", "Hello!",
        )

    def test_chat_history_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get_chat_history_async.return_value = ["line1"]

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, ["chat", "history", "winter"])

        assert result.exit_code == 0
        mock_client.get_chat_history_async.assert_called_once_with(
            "nmdcs://wintermute:411", max_lines=50,
        )

    def test_search_clear_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, [
                "search", "clear", "--hub", "winter",
            ])

        assert result.exit_code == 0
        mock_client.clear_search_results_async.assert_called_once_with(
            "nmdcs://wintermute:411",
        )

    def test_search_results_resolves_alias(self, alias_file, runner):
        add_alias("winter", "nmdcs://wintermute:411")
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get_search_results_async.return_value = []

        with patch("eiskaltdcpp.cli._get_client", return_value=mock_client):
            result = runner.invoke(cli, [
                "search", "results", "--hub", "winter",
            ])

        assert result.exit_code == 0
        mock_client.get_search_results_async.assert_called_once_with(
            "nmdcs://wintermute:411",
        )
