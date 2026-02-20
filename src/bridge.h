/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * Copyright (C) 2026 Verlihub Team
 * Licensed under GPL-3.0-or-later
 *
 * bridge.h — Main bridge class wrapping libeiskaltdcpp for Python.
 *
 * Modeled on eiskaltdcpp-daemon's ServerThread — this class initializes the
 * dcpp core, implements all listener interfaces, and exposes a clean C++ API
 * that SWIG wraps for Python.
 */

#pragma once

#include <string>
#include <vector>
#include <cstdint>
#include <mutex>
#include <atomic>
#include <deque>
#include <unordered_map>

#include "types.h"

// Forward declare the callback interface
namespace eiskaltdcpp_py {
class DCClientCallback;
}

// Forward declare dcpp types we use (avoid including heavy headers here)
namespace dcpp {
class Client;
class SearchResult;
class DirectoryListing;
}

namespace eiskaltdcpp_py {

/**
 * Main bridge class — the single entry point from Python into libeiskaltdcpp.
 *
 * Lifecycle:
 *   1. Construct a DCBridge instance
 *   2. Call initialize(configDir)
 *   3. Optionally setCallback(handler) for events
 *   4. Use connectHub(), search(), addToQueue(), etc.
 *   5. Call shutdown() when done
 *
 * Thread safety:
 *   All public methods are thread-safe. The dcpp core runs its own threads
 *   internally (timer, hasher, connection manager). Callback dispatch to
 *   Python is handled by SWIG directors which acquire the GIL automatically.
 */
class DCBridge {
public:
    DCBridge();
    ~DCBridge();

    // Non-copyable
    DCBridge(const DCBridge&) = delete;
    DCBridge& operator=(const DCBridge&) = delete;

    // =====================================================================
    // Lifecycle
    // =====================================================================

    /// Initialize the DC core library.
    /// @param configDir  Config directory for DCPlusPlus.xml, certs, etc.
    ///                   If empty, uses ~/.eiskaltdcpp-py/
    /// @return true on success
    bool initialize(const std::string& configDir = "");

    /// Shut down cleanly — disconnects all hubs, saves state.
    void shutdown();

    /// Whether initialize() has been called successfully.
    bool isInitialized() const;

    // =====================================================================
    // Callbacks
    // =====================================================================

    /// Set event callback handler. Pass nullptr to disable.
    /// Caller retains ownership of the callback object.
    void setCallback(DCClientCallback* cb);

    // =====================================================================
    // Hub connections
    // =====================================================================

    /// Connect to a hub.
    /// @param url       e.g. "dchub://example.com:411" or "adc://..."
    /// @param encoding  e.g. "CP1252", empty = UTF-8
    void connectHub(const std::string& url,
                    const std::string& encoding = "");

    /// Disconnect from a hub.
    void disconnectHub(const std::string& url);

    /// List all connected/connecting hubs.
    std::vector<HubInfo> listHubs();

    /// Check if connected to a specific hub.
    bool isHubConnected(const std::string& hubUrl);

    // =====================================================================
    // Chat
    // =====================================================================

    /// Send public chat message.
    void sendMessage(const std::string& hubUrl,
                     const std::string& message);

    /// Send private message.
    void sendPM(const std::string& hubUrl,
                const std::string& nick,
                const std::string& message);

    /// Get buffered chat history for a hub (most recent lines).
    std::vector<std::string> getChatHistory(const std::string& hubUrl,
                                            int maxLines = 50);

    // =====================================================================
    // Users
    // =====================================================================

    /// Get user list for a hub.
    std::vector<UserInfo> getHubUsers(const std::string& hubUrl);

    /// Get info for a specific user.
    UserInfo getUserInfo(const std::string& nick,
                         const std::string& hubUrl);

    // =====================================================================
    // Search
    // =====================================================================

    /// Send a search.
    /// @param query     Search string (or TTH for type=8)
    /// @param fileType  0=any,1=audio,2=compressed,3=document,4=exe,
    ///                  5=picture,6=video,7=directory,8=TTH
    /// @param sizeMode  0=don't care, 1=at least, 2=at most
    /// @param size      Size in bytes (0 = don't care)
    /// @param hubUrl    If non-empty, search only this hub
    /// @return true if search was dispatched
    bool search(const std::string& query,
                int fileType = 0,
                int sizeMode = 0,
                int64_t size = 0,
                const std::string& hubUrl = "");

    /// Get accumulated search results.
    std::vector<SearchResultInfo> getSearchResults(
        const std::string& hubUrl = "");

    /// Clear search results.
    void clearSearchResults(const std::string& hubUrl = "");

    // =====================================================================
    // Download queue
    // =====================================================================

    /// Add a file to the download queue.
    bool addToQueue(const std::string& directory,
                    const std::string& name,
                    int64_t size,
                    const std::string& tth);

    /// Add a magnet link.
    bool addMagnet(const std::string& magnetLink,
                   const std::string& downloadDir = "");

    /// Remove an item from the queue.
    void removeFromQueue(const std::string& target);

    /// Move a queued item.
    void moveQueueItem(const std::string& source,
                       const std::string& target);

    /// Set queue item priority (0=paused..5=highest).
    void setPriority(const std::string& target, int priority);

    /// List all items in the download queue.
    std::vector<QueueItemInfo> listQueue();

    /// Clear entire download queue.
    void clearQueue();

    /// Match all downloaded file lists against queue.
    void matchAllLists();

    // =====================================================================
    // File lists
    // =====================================================================

    /// Request a file list from a user.
    bool requestFileList(const std::string& hubUrl,
                         const std::string& nick,
                         bool matchQueue = false);

    /// List locally available file list files.
    std::vector<std::string> listLocalFileLists();

    /// Open a downloaded file list for browsing.
    bool openFileList(const std::string& fileListId);

    /// Browse a directory in an opened file list.
    std::vector<FileListEntry> browseFileList(
        const std::string& fileListId,
        const std::string& directory = "/");

    /// Download a file from an opened file list.
    bool downloadFileFromList(const std::string& fileListId,
                              const std::string& filePath,
                              const std::string& downloadTo);

    /// Download a directory from an opened file list.
    bool downloadDirFromList(const std::string& fileListId,
                             const std::string& dirPath,
                             const std::string& downloadTo);

    /// Close an opened file list.
    void closeFileList(const std::string& fileListId);

    /// Close all opened file lists.
    void closeAllFileLists();

    // =====================================================================
    // Sharing
    // =====================================================================

    /// Add a directory to share.
    bool addShareDir(const std::string& realPath,
                     const std::string& virtualName);

    /// Remove a directory from share.
    bool removeShareDir(const std::string& realPath);

    /// Rename a shared directory's virtual name.
    bool renameShareDir(const std::string& realPath,
                        const std::string& newVirtName);

    /// List shared directories.
    std::vector<ShareDirInfo> listShare();

    /// Refresh (rescan) shared directories.
    void refreshShare();

    /// Get total share size.
    int64_t getShareSize();

    /// Get total shared file count.
    int64_t getSharedFileCount();

    // =====================================================================
    // Transfers
    // =====================================================================

    /// Get aggregate transfer statistics.
    TransferStats getTransferStats();

    // =====================================================================
    // Hashing
    // =====================================================================

    /// Get hash progress.
    HashStatus getHashStatus();

    /// Pause/resume hashing.
    void pauseHashing(bool pause = true);

    // =====================================================================
    // Settings
    // =====================================================================

    /// Get a setting by name.
    std::string getSetting(const std::string& name);

    /// Set a setting by name.
    void setSetting(const std::string& name, const std::string& value);

    /// Reload configuration from disk.
    void reloadConfig();

    /// (Re)start the networking stack — opens TCP/UDP listeners based on
    /// current connection settings.  Call after changing InPort,
    /// ExternalIp, IncomingConnections, etc.
    void startNetworking();

    // =====================================================================
    // Lua scripting
    // =====================================================================

    /// Check if the library was compiled with Lua scripting support.
    bool luaIsAvailable() const;

    /// Evaluate a Lua code chunk.  Returns "" on success, error string on failure.
    std::string luaEval(const std::string& code);

    /// Evaluate a Lua script file.  Returns "" on success, error string on failure.
    std::string luaEvalFile(const std::string& path);

    /// Get the scripts directory path (config_dir/scripts/).
    std::string luaGetScriptsPath() const;

    /// List Lua script files in the scripts directory.
    std::vector<std::string> luaListScripts() const;

    // =====================================================================
    // Version info
    // =====================================================================

    /// Get libeiskaltdcpp version string.
    static std::string getVersion();

    // BridgeListeners needs access to hub data for stashing chat/results
    friend class BridgeListeners;

private:
    // Internal types matching ServerThread pattern
    struct HubData {
        dcpp::Client* client = nullptr;
        std::deque<std::string> chatHistory;
        std::vector<SearchResultInfo> searchResults;
        // Per-hub user map: nick → UserInfo, populated by
        // ClientListener::UserUpdated / UserRemoved callbacks.
        std::unordered_map<std::string, UserInfo> users;
    };

    // State
    std::atomic<bool> m_initialized{false};
    DCClientCallback* m_callback = nullptr;
    mutable std::mutex m_mutex;
    std::string m_configDir;  // resolved config directory (with trailing slash)

    // Hub tracking (url → data)
    std::unordered_map<std::string, HubData> m_hubs;

    // File list tracking
    std::unordered_map<std::string, dcpp::DirectoryListing*> m_fileLists;

    // Internal helpers
    HubData* findHub(const std::string& url);
    dcpp::Client* findClient(const std::string& url);

    // Maximum chat history lines per hub
    static const size_t MAX_CHAT_LINES = 100;
};

} // namespace eiskaltdcpp_py
