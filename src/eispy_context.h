/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * Copyright (C) 2026 Verlihub Team
 * Licensed under GPL-3.0-or-later
 *
 * eispy_context.h — EisPyContext: the single entry point from Python
 *                   into libeiskaltdcpp.
 *
 * Replaces the former DCBridge class.  Orchestration-only API: hub caching,
 * listener multiplexing, chat/search result caches, file list management,
 * Lua scripting, and lifecycle.  Simple pass-throughs (share size, queue
 * remove, settings get/set, etc.) are now direct SWIG calls to the
 * underlying dcpp managers via DCContext.
 */

#pragma once

#include <string>
#include <vector>
#include <cstdint>
#include <memory>
#include <mutex>
#include <atomic>
#include <deque>
#include <unordered_map>
#include <stdexcept>

#include "types.h"

// Forward declare the callback interface
namespace eiskaltdcpp_py {
class DCClientCallback;
}

// Forward declare dcpp types we use (avoid including heavy headers here)
namespace dcpp {
class Client;
class DCContext;
class SearchResult;
class DirectoryListing;
class NmdcHub;
}

// Forward declare the listener multiplexer (defined in bridge_listeners.h)
namespace eiskaltdcpp_py {
class BridgeListeners;
}

// Forward declare listener adapter classes (defined in listener_adapters.h)
namespace eiskaltdcpp_py {
class PyClientListener;
class PyClientManagerListener;
class PySearchManagerListener;
class PyQueueManagerListener;
class PyDownloadManagerListener;
class PyUploadManagerListener;
class PyTimerManagerListener;
}

namespace eiskaltdcpp_py {

// =====================================================================
// Lua exception hierarchy
// =====================================================================

/// Base exception for all Lua scripting errors.
class LuaError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// Lua is not available (library not compiled with LUA_SCRIPT).
class LuaNotAvailableError : public LuaError {
public:
    LuaNotAvailableError()
        : LuaError("Lua not available (library not compiled with LUA_SCRIPT)") {}
};

/// Lua C API symbols could not be resolved at runtime.
class LuaSymbolError : public LuaError {
public:
    LuaSymbolError()
        : LuaError("cannot resolve Lua C API symbols") {}
};

/// A Lua chunk failed to compile (syntax error).
class LuaLoadError : public LuaError {
public:
    using LuaError::LuaError;
};

/// A Lua chunk compiled but raised a runtime error.
class LuaRuntimeError : public LuaError {
public:
    using LuaError::LuaError;
};

/**
 * Main context class — the single entry point from Python into libeiskaltdcpp.
 *
 * Lifecycle:
 *   1. Construct an EisPyContext instance
 *   2. Call initialize(configDir)
 *   3. Optionally setCallback(handler) for events
 *   4. Use connectHub(), search(), addToQueue(), etc.
 *   5. Call shutdown() when done
 *
 * For simple manager operations (settings, share stats, queue remove/move,
 * hashing control, etc.), use the DCContext manager accessors directly
 * through SWIG instead of going through this class.
 *
 * Thread safety:
 *   All public methods are thread-safe. The dcpp core runs its own threads
 *   internally (timer, hasher, connection manager). Callback dispatch to
 *   Python is handled by SWIG directors which acquire the GIL automatically.
 */
class EisPyContext {
public:
    EisPyContext();
    ~EisPyContext();

    // Non-copyable
    EisPyContext(const EisPyContext&) = delete;
    EisPyContext& operator=(const EisPyContext&) = delete;

    // =====================================================================
    // Lifecycle
    // =====================================================================

    /// Initialize the DC core library (full startup: network, TLS, threads).
    bool initialize(const std::string& configDir = "");

    /// Lightweight initialization: only settings, resources, and logging.
    /// No TLS, no background threads, no network.  Intended for unit tests
    /// and tools that only read/write settings.
    bool initializeMinimal(const std::string& configDir = "");

    /// Shut down cleanly — disconnects all hubs, saves state.
    void shutdown();

    /// Whether initialize() has been called successfully.
    bool isInitialized() const;

    /// Access the underlying DCContext (may be global or per-instance).
    dcpp::DCContext* getDCContext() const { return m_context; }

    // =====================================================================
    // Callbacks
    // =====================================================================

    /// Set event callback handler. Pass nullptr to disable.
    void setCallback(DCClientCallback* cb);

    // =====================================================================
    // Hub connections
    // =====================================================================

    void connectHub(const std::string& url,
                    const std::string& encoding = "");
    void disconnectHub(const std::string& url);
    std::vector<HubInfo> listHubs();
    bool isHubConnected(const std::string& hubUrl);

    // =====================================================================
    // Chat
    // =====================================================================

    void sendMessage(const std::string& hubUrl,
                     const std::string& message);
    void sendPM(const std::string& hubUrl,
                const std::string& nick,
                const std::string& message);
    std::vector<std::string> getChatHistory(const std::string& hubUrl,
                                            int maxLines = 50);

    // =====================================================================
    // NMDCpb protobuf messaging
    // =====================================================================

    /// Send a $PB broadcast to the hub (requires hub NMDCpb support).
    /// @param hubUrl     Hub URL
    /// @param base64data Base64url-encoded PbEnvelope
    void pbBroadcast(const std::string& hubUrl,
                     const std::string& base64data);

    /// Send a $PBR routed message to a specific user via the hub.
    /// @param hubUrl     Hub URL
    /// @param toNick     Recipient nick
    /// @param base64data Base64url-encoded PbEnvelope
    void pbRouted(const std::string& hubUrl,
                  const std::string& toNick,
                  const std::string& base64data);

    /// Check if a hub supports the NMDCpb extension.
    bool hubSupportsNmdcPb(const std::string& hubUrl);

    // =====================================================================
    // NMDCpb Channels (client-side ChannelManager, per hub)
    // =====================================================================

    /// Request the hub's channel list (fires onChannelListUpdated).
    bool channelList(const std::string& hubUrl);
    /// Create a channel. isPrivate → sender-key group encryption.
    bool channelCreate(const std::string& hubUrl, const std::string& channelId,
                       const std::string& name, const std::string& topic,
                       bool isPrivate);
    /// Delete a channel (owner/admin only, enforced by the hub).
    bool channelDelete(const std::string& hubUrl, const std::string& channelId);
    /// Join a channel.
    bool channelJoin(const std::string& hubUrl, const std::string& channelId);
    /// Leave a channel.
    bool channelLeave(const std::string& hubUrl, const std::string& channelId);
    /// Set a channel topic.
    bool channelSetTopic(const std::string& hubUrl, const std::string& channelId,
                         const std::string& topic);
    /// Kick a member from a channel.
    bool channelKick(const std::string& hubUrl, const std::string& channelId,
                     const std::string& nick, const std::string& reason);
    /// Change a member's role (0=member,1=admin,2=owner,3=readonly).
    bool channelSetRole(const std::string& hubUrl, const std::string& channelId,
                        const std::string& nick, int role);
    /// Invite a user to a (private) channel.
    bool channelInvite(const std::string& hubUrl, const std::string& channelId,
                       const std::string& targetNick);
    /// Send an encrypted message to a private channel. Requires a sender key
    /// (see channelGenerateSenderKey). Returns false if none is set.
    bool channelSendMessage(const std::string& hubUrl, const std::string& channelId,
                            const std::string& text, bool isAction);

    /// Generate a fresh sender key for a private channel (become the sender).
    /// Returns a SenderKeyPy whose keyHex is the 64-char hex of the 32-byte
    /// key (empty on failure), plus keyId/generation to distribute to peers.
    SenderKeyPy channelGenerateSenderKey(const std::string& hubUrl,
                                         const std::string& channelId);
    /// Register a peer's distributed sender key for decryption. keyHex must be
    /// the 64-char hex encoding of the peer's 32-byte key.
    bool channelAddPeerSenderKey(const std::string& hubUrl,
                                 const std::string& channelId,
                                 const std::string& nick, uint32_t keyId,
                                 const std::string& keyHex);
    /// Whether we currently hold an outgoing sender key for a channel.
    bool channelHasSenderKey(const std::string& hubUrl, const std::string& channelId);

    /// Snapshot of all known channels for a hub.
    std::vector<ChannelInfoPy> getChannels(const std::string& hubUrl);
    /// Whether we have joined a given channel.
    bool isJoinedChannel(const std::string& hubUrl, const std::string& channelId);

    // =====================================================================
    // NMDCpb Calls (client-side CallManager, per hub)
    // =====================================================================

    /// Start a call. media is a list of ints (0=audio,1=video,2=screen-share).
    /// Returns the new call_id (empty on failure).
    std::string callOffer(const std::string& hubUrl, const std::string& targetNick,
                          const std::vector<int>& media, bool isGroup,
                          const std::string& groupId);
    /// Answer an incoming call. accepted=false rejects with rejectReason.
    bool callAnswer(const std::string& hubUrl, const std::string& callId,
                    bool accepted, const std::string& rejectReason);
    /// Send a connectivity candidate for an in-progress call.
    bool callCandidate(const std::string& hubUrl, const std::string& callId,
                       const std::string& candidate);
    /// End a call. reason: 0=normal,1=timeout,2=error,3=rejected,4=busy.
    bool callEnd(const std::string& hubUrl, const std::string& callId, int reason);
    /// Update our in-call media state.
    bool callMediaControl(const std::string& hubUrl, const std::string& callId,
                          bool audioMuted, bool videoMuted, bool screenSharing);

    /// Snapshot of all known calls for a hub.
    std::vector<CallInfoPy> getCalls(const std::string& hubUrl);
    /// Snapshot of only the active calls for a hub.
    std::vector<CallInfoPy> getActiveCalls(const std::string& hubUrl);

    // =====================================================================
    // Users
    // =====================================================================

    std::vector<UserInfo> getHubUsers(const std::string& hubUrl);
    UserInfo getUserInfo(const std::string& nick,
                         const std::string& hubUrl);

    // =====================================================================
    // Search
    // =====================================================================

    bool search(const std::string& query,
                int fileType = 0,
                int sizeMode = 0,
                int64_t size = 0,
                const std::string& hubUrl = "");
    std::vector<SearchResultInfo> getSearchResults(
        const std::string& hubUrl = "");
    void clearSearchResults(const std::string& hubUrl = "");

    // =====================================================================
    // Download queue (orchestration-heavy methods only)
    // =====================================================================

    bool addToQueue(const std::string& directory,
                    const std::string& name,
                    int64_t size,
                    const std::string& tth);
    bool addMagnet(const std::string& magnetLink,
                   const std::string& downloadDir = "");
    std::vector<QueueItemInfo> listQueue();
    void clearQueue();
    void matchAllLists();

    // =====================================================================
    // File lists
    // =====================================================================

    bool requestFileList(const std::string& hubUrl,
                         const std::string& nick,
                         bool matchQueue = false);
    std::vector<std::string> listLocalFileLists();
    bool openFileList(const std::string& fileListId);
    std::vector<FileListEntry> browseFileList(
        const std::string& fileListId,
        const std::string& directory = "/");
    bool downloadFileFromList(const std::string& fileListId,
                              const std::string& filePath,
                              const std::string& downloadTo);
    bool downloadDirFromList(const std::string& fileListId,
                             const std::string& dirPath,
                             const std::string& downloadTo);
    void closeFileList(const std::string& fileListId);
    void closeAllFileLists();

    // =====================================================================
    // Sharing (only addShareDir — has trailing-separator workaround)
    // =====================================================================

    bool addShareDir(const std::string& realPath,
                     const std::string& virtualName);

    // =====================================================================
    // Networking
    // =====================================================================

    void startNetworking();

    // =====================================================================
    // Lua scripting
    // =====================================================================

    bool luaIsAvailable() const;
    void luaEval(const std::string& code);
    void luaEvalFile(const std::string& path);
    std::string luaGetScriptsPath() const;
    std::vector<std::string> luaListScripts() const;

    // =====================================================================
    // Version info
    // =====================================================================

    static std::string getVersion();

    // =====================================================================
    // Per-manager listener subscription (Phase 4 — SWIG directors)
    // =====================================================================

    /// Attach a per-hub listener (ClientListener events for one hub).
    void addHubListener(const std::string& hubUrl, PyClientListener* listener);
    void removeHubListener(const std::string& hubUrl, PyClientListener* listener);

    /// Global ClientManagerListener (user/hub lifecycle across all hubs).
    void addClientManagerListener(PyClientManagerListener* listener);
    void removeClientManagerListener(PyClientManagerListener* listener);

    /// Global SearchManagerListener.
    void addSearchListener(PySearchManagerListener* listener);
    void removeSearchListener(PySearchManagerListener* listener);

    /// Global QueueManagerListener.
    void addQueueListener(PyQueueManagerListener* listener);
    void removeQueueListener(PyQueueManagerListener* listener);

    /// Global DownloadManagerListener.
    void addDownloadListener(PyDownloadManagerListener* listener);
    void removeDownloadListener(PyDownloadManagerListener* listener);

    /// Global UploadManagerListener.
    void addUploadListener(PyUploadManagerListener* listener);
    void removeUploadListener(PyUploadManagerListener* listener);

    /// Global TimerManagerListener.
    void addTimerListener(PyTimerManagerListener* listener);
    void removeTimerListener(PyTimerManagerListener* listener);

    // BridgeListeners needs access to hub data for stashing chat/results
    friend class BridgeListeners;

private:
    // Internal types matching ServerThread pattern
    struct HubData {
        dcpp::Client* client = nullptr;
        std::deque<std::string> chatHistory;
        std::vector<SearchResultInfo> searchResults;
        std::unordered_map<std::string, UserInfo> users;
        HubInfo cachedInfo;
    };

    // State
    std::atomic<bool> m_initialized{false};
    dcpp::DCContext* m_context = nullptr;  // non-owning; shared global
    std::unique_ptr<dcpp::DCContext> m_ownedContext;  // owned by this instance (minimal mode)
    DCClientCallback* m_callback = nullptr;
    mutable std::mutex m_mutex;
    std::string m_configDir;

    // Hub tracking (url → data)
    std::unordered_map<std::string, HubData> m_hubs;

    // Listener multiplexer (bridges dcpp callbacks to Python)
    std::unique_ptr<BridgeListeners> m_listeners;

    // File list tracking
    std::unordered_map<std::string, dcpp::DirectoryListing*> m_fileLists;

    // Internal helpers
    HubData* findHub(const std::string& url);
    dcpp::Client* findClient(const std::string& url);
    /// Find the NmdcHub for a URL (nullptr if not an NMDC hub / not found).
    /// Locks m_mutex internally; the caller MUST NOT hold m_mutex.
    dcpp::NmdcHub* findNmdcHub(const std::string& url);

    // Shared initialization helpers
    static std::string resolveConfigDir(const std::string& configDir);
    void applyDefaults(const std::string& cfgDir);

    // Maximum chat history lines per hub
    static const size_t MAX_CHAT_LINES = 100;
};

/// Backward compatibility alias
using DCBridge = EisPyContext;

} // namespace eiskaltdcpp_py
