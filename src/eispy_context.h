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
}

// Forward declare the listener multiplexer (defined in bridge_listeners.h)
namespace eiskaltdcpp_py {
class BridgeListeners;
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

    /// Initialize the DC core library.
    bool initialize(const std::string& configDir = "");

    /// Shut down cleanly — disconnects all hubs, saves state.
    void shutdown();

    /// Whether initialize() has been called successfully.
    bool isInitialized() const;

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
    std::unique_ptr<dcpp::DCContext> m_context;
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

    // Maximum chat history lines per hub
    static const size_t MAX_CHAT_LINES = 100;
};

/// Backward compatibility alias
using DCBridge = EisPyContext;

} // namespace eiskaltdcpp_py
