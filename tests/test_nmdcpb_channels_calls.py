"""
Tests for the NMDCpb Channels & Calls SWIG bindings.

These cover the client-side ChannelManager / CallManager surface exposed
through the SWIG bridge (EisPyContext / DCBridge):

  * the Python-friendly snapshot structs (ChannelInfoPy, CallInfoPy,
    ChannelMemberInfo) and their std::vector templates,
  * the DCClientCallback channel/call director virtuals (existence,
    direct invocation, Python subclass override), and
  * the DCBridge action/query methods, including their safe no-op
    behaviour when no matching NMDC hub is connected.

A live verlihub connection is out of scope here (covered by integration
tests); without a connected NMDC hub the action methods must fail closed
(return False / empty) rather than crash.
"""
import sys
from pathlib import Path

import pytest

BUILD_DIR = Path(__file__).parent.parent / "build" / "python"
if BUILD_DIR.exists():
    sys.path.insert(0, str(BUILD_DIR))

try:
    from eiskaltdcpp import dc_core
    SWIG_AVAILABLE = True
except ImportError:
    SWIG_AVAILABLE = False
    dc_core = None

# The channel/call surface only exists when the core was built WITH_NMDCPB.
NMDCPB_AVAILABLE = SWIG_AVAILABLE and hasattr(dc_core, "ChannelInfoPy")

pytestmark = pytest.mark.skipif(
    not NMDCPB_AVAILABLE,
    reason="dc_core built without NMDCpb (ChannelInfoPy missing)",
)

NO_HUB = "dchub://not-connected.invalid:411"


# ============================================================================
# Snapshot struct types
# ============================================================================

class TestChannelStructTypes:
    def test_channel_member_defaults(self):
        m = dc_core.ChannelMemberInfo()
        assert m.nick == ""
        assert m.role == 0

    def test_channel_member_mutation(self):
        m = dc_core.ChannelMemberInfo()
        m.nick = "alice"
        m.role = 2  # owner
        assert m.nick == "alice"
        assert m.role == 2

    def test_channel_info_defaults(self):
        ch = dc_core.ChannelInfoPy()
        assert ch.channelId == ""
        assert ch.name == ""
        assert ch.topic == ""
        assert ch.isPrivate is False
        assert ch.ownerNick == ""
        assert ch.createdAt == 0
        assert ch.memberCount == 0
        assert ch.joined is False
        assert len(ch.members) == 0

    def test_channel_info_mutation(self):
        ch = dc_core.ChannelInfoPy()
        ch.channelId = "general"
        ch.name = "General"
        ch.topic = "Welcome"
        ch.isPrivate = True
        ch.ownerNick = "op"
        ch.createdAt = 1234567890
        ch.memberCount = 5
        ch.joined = True
        assert ch.channelId == "general"
        assert ch.name == "General"
        assert ch.topic == "Welcome"
        assert ch.isPrivate is True
        assert ch.ownerNick == "op"
        assert ch.createdAt == 1234567890
        assert ch.memberCount == 5
        assert ch.joined is True

    def test_channel_info_members_vector(self):
        ch = dc_core.ChannelInfoPy()
        m = dc_core.ChannelMemberInfo()
        m.nick = "bob"
        m.role = 1
        ch.members.append(m)
        assert len(ch.members) == 1
        assert ch.members[0].nick == "bob"
        assert ch.members[0].role == 1

    def test_sender_key_defaults(self):
        sk = dc_core.SenderKeyPy()
        assert sk.keyHex == ""
        assert sk.keyId == 0
        assert sk.generation == 0

    def test_sender_key_mutation(self):
        sk = dc_core.SenderKeyPy()
        sk.keyHex = "ab" * 32
        sk.keyId = 3
        sk.generation = 1
        assert sk.keyHex == "ab" * 32
        assert sk.keyId == 3
        assert sk.generation == 1


class TestCallStructTypes:
    def test_call_info_defaults(self):
        c = dc_core.CallInfoPy()
        assert c.callId == ""
        assert c.peerNick == ""
        assert c.isGroup is False
        assert c.groupId == ""
        assert len(c.media) == 0
        assert c.state == 0
        assert c.createdAt == 0
        assert c.answeredAt == 0
        assert c.localAudioMuted is False
        assert c.localVideoMuted is False
        assert c.localScreenSharing is False
        assert c.remoteAudioMuted is False
        assert c.remoteVideoMuted is False
        assert c.remoteScreenSharing is False

    def test_call_info_mutation(self):
        c = dc_core.CallInfoPy()
        c.callId = "abc-123"
        c.peerNick = "carol"
        c.isGroup = True
        c.groupId = "grp1"
        c.state = 2  # active
        c.createdAt = 111
        c.answeredAt = 222
        c.localAudioMuted = True
        c.remoteScreenSharing = True
        assert c.callId == "abc-123"
        assert c.peerNick == "carol"
        assert c.isGroup is True
        assert c.groupId == "grp1"
        assert c.state == 2
        assert c.createdAt == 111
        assert c.answeredAt == 222
        assert c.localAudioMuted is True
        assert c.remoteScreenSharing is True

    def test_call_info_media_vector(self):
        c = dc_core.CallInfoPy()
        c.media.append(0)  # audio
        c.media.append(1)  # video
        assert list(c.media) == [0, 1]


# ============================================================================
# std::vector template wrappers
# ============================================================================

class TestVectorTemplates:
    def test_int_vector(self):
        v = dc_core.IntVector()
        v.append(0)
        v.append(2)
        assert list(v) == [0, 2]

    def test_channel_member_vector(self):
        v = dc_core.ChannelMemberVector()
        m = dc_core.ChannelMemberInfo()
        m.nick = "dave"
        v.append(m)
        assert len(v) == 1
        assert v[0].nick == "dave"

    def test_channel_info_vector(self):
        v = dc_core.ChannelInfoVector()
        ch = dc_core.ChannelInfoPy()
        ch.channelId = "x"
        v.append(ch)
        assert len(v) == 1
        assert v[0].channelId == "x"

    def test_call_info_vector(self):
        v = dc_core.CallInfoVector()
        c = dc_core.CallInfoPy()
        c.callId = "y"
        v.append(c)
        assert len(v) == 1
        assert v[0].callId == "y"


# ============================================================================
# DCClientCallback channel/call director virtuals
# ============================================================================

class TestChannelCallCallbacks:
    CHANNEL_CALLBACKS = [
        "onChannelListUpdated",
        "onChannelCreated",
        "onChannelMemberUpdate",
        "onChannelMessage",
        "onChannelInvite",
        "onChannelMessageUndecryptable",
        "onSenderKeyRotation",
    ]
    CALL_CALLBACKS = [
        "onCallOffer",
        "onCallAnswer",
        "onCallCandidate",
        "onCallEnd",
        "onCallMediaControl",
    ]

    @pytest.mark.parametrize("name", CHANNEL_CALLBACKS + CALL_CALLBACKS)
    def test_callback_exists(self, name):
        cb = dc_core.DCClientCallback()
        assert hasattr(cb, name)
        assert callable(getattr(cb, name))

    def test_default_callbacks_are_noops(self):
        cb = dc_core.DCClientCallback()
        cb.onChannelListUpdated(NO_HUB)
        cb.onChannelCreated(NO_HUB, "general", "op", False)
        cb.onChannelMemberUpdate(NO_HUB, "general", "alice", 0, 0, "")
        cb.onChannelMessage(NO_HUB, "general", "alice", "hi", False, 0)
        cb.onChannelInvite(NO_HUB, "general", "me", "op")
        cb.onChannelMessageUndecryptable(NO_HUB, "general", "alice", 7)
        cb.onSenderKeyRotation(NO_HUB, "general", "member-left", "bob")
        cb.onCallOffer(NO_HUB, "cid", "carol", False, "0,1")
        cb.onCallAnswer(NO_HUB, "cid", "carol", True, "")
        cb.onCallCandidate(NO_HUB, "cid", "carol", "cand")
        cb.onCallEnd(NO_HUB, "cid", 0, 42)
        cb.onCallMediaControl(NO_HUB, "cid", "carol", True, False, False)

    def test_channel_callbacks_overridable(self):
        events = []

        class CB(dc_core.DCClientCallback):
            def onChannelCreated(self, hub, cid, owner, priv):
                events.append(("created", hub, cid, owner, priv))

            def onChannelMessage(self, hub, cid, frm, text, action, ts):
                events.append(("msg", cid, frm, text, action, ts))

            def onChannelMemberUpdate(self, hub, cid, nick, utype, role, reason):
                events.append(("member", cid, nick, utype, role, reason))

        cb = CB()
        cb.onChannelCreated(NO_HUB, "general", "op", True)
        cb.onChannelMessage(NO_HUB, "general", "alice", "hello", False, 99)
        cb.onChannelMemberUpdate(NO_HUB, "general", "bob", 2, 3, "kicked")

        assert events[0] == ("created", NO_HUB, "general", "op", True)
        assert events[1] == ("msg", "general", "alice", "hello", False, 99)
        assert events[2] == ("member", "general", "bob", 2, 3, "kicked")

    def test_call_callbacks_overridable(self):
        events = []

        class CB(dc_core.DCClientCallback):
            def onCallOffer(self, hub, cid, frm, is_group, media_csv):
                events.append(("offer", cid, frm, is_group, media_csv))

            def onCallEnd(self, hub, cid, reason, dur):
                events.append(("end", cid, reason, dur))

        cb = CB()
        cb.onCallOffer(NO_HUB, "call-1", "carol", True, "0,1,2")
        cb.onCallEnd(NO_HUB, "call-1", 3, 120)
        assert events[0] == ("offer", "call-1", "carol", True, "0,1,2")
        assert events[1] == ("end", "call-1", 3, 120)


# ============================================================================
# DCBridge action/query methods
# ============================================================================

class TestBridgeMethodsExist:
    CHANNEL_METHODS = [
        "channelList", "channelCreate", "channelDelete", "channelJoin",
        "channelLeave", "channelSetTopic", "channelKick", "channelSetRole",
        "channelInvite", "channelSendMessage", "channelGenerateSenderKey",
        "channelAddPeerSenderKey", "channelHasSenderKey", "getChannels",
        "isJoinedChannel",
    ]
    CALL_METHODS = [
        "callOffer", "callAnswer", "callCandidate", "callEnd",
        "callMediaControl", "getCalls", "getActiveCalls",
    ]

    @pytest.mark.parametrize("name", CHANNEL_METHODS + CALL_METHODS)
    def test_method_exists(self, name):
        assert hasattr(dc_core.DCBridge, name)
        assert callable(getattr(dc_core.DCBridge, name))


class TestBridgeNoHubBehaviour:
    """Without a connected NMDC hub every action fails closed."""

    @pytest.fixture(scope="class")
    def bridge(self, tmp_path_factory):
        cfg = tmp_path_factory.mktemp("nmdcpb-cc-tests")
        b = dc_core.EisPyContext()
        ok = b.initialize(str(cfg) + "/")
        assert ok, "Context initialization failed"
        yield b
        b.shutdown()

    # ---- Channel actions ----

    def test_channel_actions_return_false(self, bridge):
        assert bridge.channelList(NO_HUB) is False
        assert bridge.channelCreate(NO_HUB, "c", "C", "topic", False) is False
        assert bridge.channelDelete(NO_HUB, "c") is False
        assert bridge.channelJoin(NO_HUB, "c") is False
        assert bridge.channelLeave(NO_HUB, "c") is False
        assert bridge.channelSetTopic(NO_HUB, "c", "t") is False
        assert bridge.channelKick(NO_HUB, "c", "nick", "reason") is False
        assert bridge.channelSetRole(NO_HUB, "c", "nick", 1) is False
        assert bridge.channelInvite(NO_HUB, "c", "nick") is False
        assert bridge.channelSendMessage(NO_HUB, "c", "hi", False) is False
        assert bridge.channelHasSenderKey(NO_HUB, "c") is False

    def test_channel_set_role_rejects_bad_role(self, bridge):
        # out-of-range role is rejected before any hub lookup
        assert bridge.channelSetRole(NO_HUB, "c", "nick", -1) is False
        assert bridge.channelSetRole(NO_HUB, "c", "nick", 99) is False

    def test_channel_generate_sender_key_empty(self, bridge):
        # Returns a SenderKeyPy; no hub -> empty keyHex and zeroed ids.
        result = bridge.channelGenerateSenderKey(NO_HUB, "c")
        assert result.keyHex == ""
        assert result.keyId == 0
        assert result.generation == 0

    def test_channel_add_peer_sender_key_false(self, bridge):
        # 64-char hex (32-byte) key but no hub -> False
        assert bridge.channelAddPeerSenderKey(
            NO_HUB, "c", "nick", 1, "00" * 32) is False
        # wrong-size hex -> also False
        assert bridge.channelAddPeerSenderKey(
            NO_HUB, "c", "nick", 1, "abcd") is False
        # non-hex chars -> False
        assert bridge.channelAddPeerSenderKey(
            NO_HUB, "c", "nick", 1, "zz" * 32) is False

    def test_get_channels_empty(self, bridge):
        chans = bridge.getChannels(NO_HUB)
        assert len(chans) == 0

    def test_is_joined_channel_false(self, bridge):
        assert bridge.isJoinedChannel(NO_HUB, "c") is False

    # ---- Call actions ----

    def test_call_offer_empty(self, bridge):
        media = dc_core.IntVector()
        media.append(0)
        call_id = bridge.callOffer(NO_HUB, "carol", media, False, "")
        assert call_id == ""

    def test_call_offer_accepts_python_list(self, bridge):
        # SWIG accepts a Python list for the vector<int> parameter.
        call_id = bridge.callOffer(NO_HUB, "carol", [0, 1], False, "")
        assert call_id == ""

    def test_call_actions_return_false(self, bridge):
        assert bridge.callAnswer(NO_HUB, "cid", True, "") is False
        assert bridge.callAnswer(NO_HUB, "cid", False, "busy") is False
        assert bridge.callCandidate(NO_HUB, "cid", "cand") is False
        assert bridge.callEnd(NO_HUB, "cid", 0) is False
        assert bridge.callMediaControl(NO_HUB, "cid", True, False, False) is False

    def test_call_end_rejects_bad_reason(self, bridge):
        assert bridge.callEnd(NO_HUB, "cid", -1) is False
        assert bridge.callEnd(NO_HUB, "cid", 99) is False

    def test_get_calls_empty(self, bridge):
        assert len(bridge.getCalls(NO_HUB)) == 0
        assert len(bridge.getActiveCalls(NO_HUB)) == 0
