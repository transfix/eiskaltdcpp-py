"""
Tests for the high-level Python NMDCpb channel/call API on
DCClient / AsyncDCClient.

These exercise the Pythonic wrappers (snake_case methods, event
registration, SenderKeyPy struct handling) layered on top of the SWIG
bridge. They do NOT require a live NMDC hub: without a connected hub the
action methods must fail closed (return False / "" / empty list) and the
event handlers must be registerable and dispatchable.

A live verlihub round-trip is covered by the integration suite.
"""
import sys
from pathlib import Path

import pytest

BUILD_DIR = Path(__file__).parent.parent / "build" / "python"
if BUILD_DIR.exists():
    sys.path.insert(0, str(BUILD_DIR))

try:
    from eiskaltdcpp import DCClient, AsyncDCClient, dc_core
    from eiskaltdcpp.dc_client import EVENT_TYPES
    SWIG_AVAILABLE = True
except ImportError:
    SWIG_AVAILABLE = False
    DCClient = AsyncDCClient = dc_core = None
    EVENT_TYPES = frozenset()

# The channel/call surface only exists when the core was built WITH_NMDCPB.
NMDCPB_AVAILABLE = SWIG_AVAILABLE and hasattr(dc_core, "ChannelInfoPy")

pytestmark = pytest.mark.skipif(
    not NMDCPB_AVAILABLE,
    reason="dc_core built without NMDCpb (ChannelInfoPy missing)",
)

NO_HUB = "dchub://not-connected.invalid:411"

# The full set of NMDCpb events added by the high-level API.
CHANNEL_EVENTS = {
    "channel_list_updated",
    "channel_created",
    "channel_member_update",
    "channel_message",
    "channel_invite",
    "channel_message_undecryptable",
    "sender_key_rotation",
}
CALL_EVENTS = {
    "call_offer",
    "call_answer",
    "call_candidate",
    "call_end",
    "call_media_control",
}


# ---------------------------------------------------------------------------
# Event-type registration
# ---------------------------------------------------------------------------

class TestEventTypes:
    def test_channel_events_registered(self):
        assert CHANNEL_EVENTS <= EVENT_TYPES

    def test_call_events_registered(self):
        assert CALL_EVENTS <= EVENT_TYPES


# ---------------------------------------------------------------------------
# DCClient method surface
# ---------------------------------------------------------------------------

class TestDCClientMethodSurface:
    EXPECTED = {
        "channel_list", "channel_create", "channel_delete", "channel_join",
        "channel_leave", "channel_set_topic", "channel_kick",
        "channel_set_role", "channel_invite", "channel_send_message",
        "channel_generate_sender_key", "channel_add_peer_sender_key",
        "channel_has_sender_key", "get_channels", "is_joined_channel",
        "call_offer", "call_answer", "call_candidate", "call_end",
        "call_media_control", "get_calls", "get_active_calls",
    }

    def test_dcclient_has_methods(self):
        for name in self.EXPECTED:
            assert callable(getattr(DCClient, name, None)), name

    def test_async_has_methods(self):
        for name in self.EXPECTED:
            assert callable(getattr(AsyncDCClient, name, None)), name


# ---------------------------------------------------------------------------
# DCClient no-hub behaviour (fail-closed)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="class")
def client(tmp_path_factory):
    cfg = tmp_path_factory.mktemp("dc-highlevel")
    c = DCClient(str(cfg) + "/")
    assert c.initialize()
    yield c
    c.shutdown()


class TestDCClientNoHub:
    def test_channel_actions_return_false(self, client):
        assert client.channel_list(NO_HUB) is False
        assert client.channel_create(NO_HUB, "c", "Name", "Topic", True) is False
        assert client.channel_delete(NO_HUB, "c") is False
        assert client.channel_join(NO_HUB, "c") is False
        assert client.channel_leave(NO_HUB, "c") is False
        assert client.channel_set_topic(NO_HUB, "c", "t") is False
        assert client.channel_kick(NO_HUB, "c", "n", "why") is False
        assert client.channel_invite(NO_HUB, "c", "n") is False
        assert client.channel_send_message(NO_HUB, "c", "hi") is False

    def test_channel_queries_empty(self, client):
        assert client.get_channels(NO_HUB) == []
        assert client.is_joined_channel(NO_HUB, "c") is False
        assert client.channel_has_sender_key(NO_HUB, "c") is False

    def test_channel_set_role_validates(self, client):
        # valid range 0..3 but no hub -> False; out-of-range -> False too
        assert client.channel_set_role(NO_HUB, "c", "n", 1) is False
        assert client.channel_set_role(NO_HUB, "c", "n", 99) is False
        assert client.channel_set_role(NO_HUB, "c", "n", -1) is False

    def test_generate_sender_key_empty(self, client):
        sk = client.channel_generate_sender_key(NO_HUB, "c")
        assert sk.keyHex == ""
        assert sk.keyId == 0
        assert sk.generation == 0

    def test_add_peer_sender_key_false(self, client):
        # well-formed 64-char hex, but no hub -> False
        assert client.channel_add_peer_sender_key(
            NO_HUB, "c", "nick", 1, "00" * 32) is False
        # malformed hex -> False
        assert client.channel_add_peer_sender_key(
            NO_HUB, "c", "nick", 1, "abcd") is False

    def test_call_actions(self, client):
        # no hub -> callOffer returns "" (empty call id)
        assert client.call_offer(NO_HUB, "peer", [0, 1]) == ""
        assert client.call_offer(NO_HUB, "peer") == ""  # default media=[audio]
        assert client.call_answer(NO_HUB, "callid", True) is False
        assert client.call_answer(NO_HUB, "callid", False, "busy") is False
        assert client.call_candidate(NO_HUB, "callid", "cand") is False
        assert client.call_end(NO_HUB, "callid", 0) is False
        assert client.call_media_control(NO_HUB, "callid", True, False, False) is False

    def test_call_end_reason_validation(self, client):
        # valid 0..4, invalid rejected — all False (no hub) but must not raise
        for reason in (0, 1, 2, 3, 4, 5, 99, -1):
            assert client.call_end(NO_HUB, "callid", reason) is False

    def test_call_queries_empty(self, client):
        assert client.get_calls(NO_HUB) == []
        assert client.get_active_calls(NO_HUB) == []


# ---------------------------------------------------------------------------
# Event registration + dispatch
# ---------------------------------------------------------------------------

class TestEventDispatch:
    def test_register_and_dispatch_channel_message(self, client):
        received = []

        @client.on("channel_message")
        def handler(hub, channel, nick, text, is_action, ts):
            received.append((hub, channel, nick, text, is_action, ts))

        # Directly drive the router as the C++ side would.
        client._router.onChannelMessage(
            NO_HUB, "chan", "bob", "hello", False, 1234)
        assert received == [(NO_HUB, "chan", "bob", "hello", False, 1234)]
        client.off("channel_message", handler)

    def test_register_and_dispatch_call_offer(self, client):
        received = []
        client.on(
            "call_offer",
            lambda hub, cid, nick, grp, media: received.append(
                (hub, cid, nick, grp, media)),
        )
        client._router.onCallOffer(NO_HUB, "cid1", "alice", False, "0,1")
        assert received == [(NO_HUB, "cid1", "alice", False, "0,1")]

    def test_decorator_registration_for_all_events(self, client):
        # Every new event must be a valid registration target.
        for ev in CHANNEL_EVENTS | CALL_EVENTS:
            client.on(ev, lambda *a: None)

    def test_unknown_event_rejected(self, client):
        with pytest.raises(ValueError):
            client.on("channel_bogus", lambda *a: None)


# ---------------------------------------------------------------------------
# SenderKeyPy struct via high-level API
# ---------------------------------------------------------------------------

class TestSenderKeyStruct:
    def test_generate_returns_senderkey_type(self, client):
        sk = client.channel_generate_sender_key(NO_HUB, "c")
        assert isinstance(sk, dc_core.SenderKeyPy)
        # attribute access works
        assert hasattr(sk, "keyHex")
        assert hasattr(sk, "keyId")
        assert hasattr(sk, "generation")
