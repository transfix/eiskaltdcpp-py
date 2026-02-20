/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * Copyright (C) 2026 Verlihub Team
 * Licensed under GPL-3.0-or-later
 *
 * bridge.cpp — DCBridge implementation.
 *
 * This follows the patterns established by eiskaltdcpp-daemon's ServerThread
 * and ServerManager for initializing and using the dcpp core library.
 */

#include "bridge.h"
#include "bridge_listeners.h"
#include "callbacks.h"
#include "dcpp_compat.h"  // must precede dcpp headers (provides STL + using decls)

#include <dcpp/DCPlusPlus.h>
#include <dcpp/Util.h>
#include <dcpp/Client.h>
#include <dcpp/ClientManager.h>
#include <dcpp/ConnectionManager.h>
#include <dcpp/ConnectivityManager.h>
#include <dcpp/DownloadManager.h>
#include <dcpp/FavoriteManager.h>
#include <dcpp/HashManager.h>
#include <dcpp/NmdcHub.h>
#include <dcpp/QueueManager.h>
#include <dcpp/SearchManager.h>
#include <dcpp/SearchResult.h>
#include <dcpp/SettingsManager.h>
#include <dcpp/ShareManager.h>
#include <dcpp/StringTokenizer.h>
#include <dcpp/TimerManager.h>
#include <dcpp/Transfer.h>
#include <dcpp/UploadManager.h>
#include <dcpp/DirectoryListing.h>

// dcpp/version.h pulls in VersionGlobal.h which is a build-time generated
// file not installed by libeiskaltdcpp-dev.  We only need DCVERSIONSTRING.
#ifndef DCVERSIONSTRING
#define DCVERSIONSTRING "2.4.2"
#endif

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <iostream>

#include <dlfcn.h>   // dlsym — for runtime Lua scripting init
#include <unistd.h>  // getpid — for default nick generation

using namespace dcpp;

namespace eiskaltdcpp_py {

// =========================================================================
// Runtime Lua scripting initialization
// =========================================================================
// The system libeiskaltdcpp.so may be compiled with LUA_SCRIPT support.
// When it is, every incoming NMDC line passes through a Lua hook
// (NmdcHubScriptInstance::onClientMessage) which dereferences a static
// lua_State* pointer.  If ScriptManager::load() was never called, that
// pointer is null and the process segfaults.
//
// We cannot simply #include <dcpp/ScriptManager.h> because it depends on
// extra/lunar.h which is not installed by the dev package.  Instead, we
// resolve the singleton instance pointer and load() method at runtime via
// dlsym using the Itanium ABI mangled names (stable on Linux/GCC/Clang).
// =========================================================================

static void initLuaScriptingIfPresent() {
    // dcpp::ScriptInstance::L  (static protected member — lua_State* pointer)
    // Mangled: _ZN4dcpp14ScriptInstance1LE
    void** lua_state_ptr = reinterpret_cast<void**>(
        dlsym(RTLD_DEFAULT,
              "_ZN4dcpp14ScriptInstance1LE"));
    if (!lua_state_ptr)
        return;   // Not compiled with Lua — nothing to do

    if (*lua_state_ptr)
        return;   // Already initialized

    // Resolve luaL_newstate and luaL_openlibs from the loaded Lua library
    using NewStateFn = void* (*)();
    using OpenLibsFn = void (*)(void*);

    NewStateFn new_state = reinterpret_cast<NewStateFn>(
        dlsym(RTLD_DEFAULT, "luaL_newstate"));
    OpenLibsFn open_libs = reinterpret_cast<OpenLibsFn>(
        dlsym(RTLD_DEFAULT, "luaL_openlibs"));

    if (!new_state || !open_libs)
        return;

    // Initialize a minimal Lua state so that onClientMessage() doesn't crash
    // when it calls lua_pushlightuserdata(L, ...) with L == null.
    void* L = new_state();
    if (!L) return;
    open_libs(L);

    *lua_state_ptr = L;
}

// =========================================================================
// Startup callback (called by dcpp::startup)
// =========================================================================

static void startupCallback(void*, const std::string& msg) {
    // Could log this if desired
}

// =========================================================================
// Global init guard — dcpp::startup() creates global singletons and must
// only be called ONCE per process.  A second call would double-construct
// every manager and hang or crash.
// =========================================================================

static std::atomic<bool> g_dcppStarted{false};
static std::mutex        g_dcppStartupMutex;

// =========================================================================
// DCBridge — Construction / Destruction
// =========================================================================

DCBridge::DCBridge() = default;

DCBridge::~DCBridge() {
    if (m_initialized.load()) {
        shutdown();
    }
}

// =========================================================================
// Lifecycle
// =========================================================================

bool DCBridge::initialize(const std::string& configDir) {
    if (m_initialized.load()) {
        return true; // Already initialized
    }

    std::lock_guard<std::mutex> lock(m_mutex);

    // Prevent a second DCBridge from calling dcpp::startup() in the same
    // process — the singleton managers already exist and re-constructing
    // them causes hangs / undefined behaviour.
    {
        std::lock_guard<std::mutex> glock(g_dcppStartupMutex);
        if (g_dcppStarted.load()) {
            // Core is already running — refuse initialization of a second
            // bridge instance rather than risking UB.
            return false;
        }
    }

    // Set up config directory
    std::string cfgDir = configDir;
    if (cfgDir.empty()) {
        const char* home = getenv("HOME");
        if (home) {
            cfgDir = std::string(home) + "/.eiskaltdcpp-py/";
        } else {
            cfgDir = "/tmp/.eiskaltdcpp-py/";
        }
    }

    // Ensure trailing slash
    if (!cfgDir.empty() && cfgDir.back() != '/') {
        cfgDir += '/';
    }

    // Create directory if needed
    try {
        std::filesystem::create_directories(cfgDir);
    } catch (const std::exception& e) {
        return false;
    }

    // Initialize dcpp paths — must be called before dcpp::startup() which
    // internally calls Util::initialize() again, but the static guard in
    // initialize() means our overrides take precedence.
    Util::PathsMap pathOverrides;
    pathOverrides[Util::PATH_USER_CONFIG] = cfgDir;
    pathOverrides[Util::PATH_USER_LOCAL] = cfgDir;
    Util::initialize(pathOverrides);

    // Start the core library — creates all singleton managers, loads
    // settings, favorites, certificates, hashing, share refresh, and queue.
    dcpp::startup(startupCallback, nullptr);

    // Mark as globally started (must come after startup() succeeds)
    g_dcppStarted.store(true);

    // Ensure a nick is set — without one the NMDC handshake sends an empty
    // $ValidateNick which the hub rejects, leaving connected=false forever.
    {
        auto* sm = SettingsManager::getInstance();
        std::string currentNick = sm->get(SettingsManager::NICK, true);
        if (currentNick.empty()) {
            // Generate a default nick: "dcpy-<pid>"
            std::string defaultNick = "dcpy-" + std::to_string(getpid());
            sm->set(SettingsManager::NICK, defaultNick);
        }
    }

    // Initialize the Lua scripting state if the library was compiled with
    // Lua support.  Without this, NMDC hub callbacks that pass through the
    // Lua script layer will crash because the lua_State* is null.
    initLuaScriptingIfPresent();

    // Start the timer (drives periodic events) — not done by startup()
    TimerManager::getInstance()->start();

    // Subscribe listeners to global managers
    BridgeListeners::getInstance().setBridge(this);
    BridgeListeners::getInstance().subscribeGlobal();

    m_initialized.store(true);
    return true;
}

void DCBridge::shutdown() {
    if (!m_initialized.load()) {
        return;
    }

    // Unsubscribe from global managers (safe without m_mutex —
    // these are single-threaded calls that don't touch m_hubs)
    BridgeListeners::getInstance().unsubscribeGlobal();
    BridgeListeners::getInstance().setBridge(nullptr);
    BridgeListeners::getInstance().setCallback(nullptr);

    // Collect hub clients and file lists under the lock, then release
    std::vector<Client*> clients;
    {
        std::lock_guard<std::mutex> lock(m_mutex);

        // Close all file lists
        for (auto& [id, listing] : m_fileLists) {
            delete listing;
        }
        m_fileLists.clear();

        // Collect hub clients
        for (auto& [url, data] : m_hubs) {
            if (data.client) {
                clients.push_back(data.client);
            }
        }
        m_hubs.clear();
    }

    // m_mutex released — safe to call into dcpp (avoids ABBA deadlock)
    for (auto* client : clients) {
        client->disconnect(true);
        ClientManager::getInstance()->putClient(client);
    }

    // Shut down core library
    dcpp::shutdown();

    m_initialized.store(false);
}

bool DCBridge::isInitialized() const {
    return m_initialized.load();
}

// =========================================================================
// Callbacks
// =========================================================================

void DCBridge::setCallback(DCClientCallback* cb) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_callback = cb;
    BridgeListeners::getInstance().setCallback(cb);
}

// =========================================================================
// Hub connections
// =========================================================================

void DCBridge::connectHub(const std::string& url,
                          const std::string& encoding) {
    if (!m_initialized.load()) return;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        // Don't connect twice
        if (m_hubs.count(url) > 0) return;
    }

    // m_mutex released — safe to call into dcpp (avoids ABBA deadlock
    // with ClientManager::cs / NmdcHub::cs held by hub socket threads)
    Client* client = ClientManager::getInstance()->getClient(url);
    if (!client) return;

    if (!encoding.empty()) {
        client->setEncoding(encoding);
    }

    // Register ourselves as listener (via the BridgeListeners helper)
    BridgeListeners::getInstance().attach(client, this);

    client->connect();

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        HubData hd;
        hd.client = client;
        m_hubs[url] = std::move(hd);
    }
}

void DCBridge::disconnectHub(const std::string& url) {
    if (!m_initialized.load()) return;

    Client* client = nullptr;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto it = m_hubs.find(url);
        if (it == m_hubs.end()) return;
        client = it->second.client;
        m_hubs.erase(it);
    }

    // m_mutex released — safe to call into dcpp (avoids ABBA deadlock)
    if (client) {
        BridgeListeners::getInstance().detach(client);
        client->disconnect(true);
        ClientManager::getInstance()->putClient(client);
    }
}

std::vector<HubInfo> DCBridge::listHubs() {
    std::vector<HubInfo> result;
    if (!m_initialized.load()) return result;

    // Snapshot the url→client pointers under the lock
    std::vector<std::pair<std::string, Client*>> snapshot;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        snapshot.reserve(m_hubs.size());
        for (auto& [url, data] : m_hubs) {
            snapshot.emplace_back(url, data.client);
        }
    }

    // m_mutex released — safe to call dcpp accessors (avoids ABBA deadlock)
    for (auto& [url, client] : snapshot) {
        HubInfo info;
        info.url = url;
        if (client) {
            info.name = client->getHubName();
            info.description = client->getHubDescription();
            info.userCount = client->getUserCount();
            info.sharedBytes = client->getAvailable();
            info.connected = client->isConnected();
            info.isOp = client->isOp();
        }
        result.push_back(std::move(info));
    }
    return result;
}

bool DCBridge::isHubConnected(const std::string& hubUrl) {
    if (!m_initialized.load()) return false;

    std::lock_guard<std::mutex> lock(m_mutex);
    auto* client = findClient(hubUrl);
    return client && client->isConnected();
}

// =========================================================================
// Chat
// =========================================================================

void DCBridge::sendMessage(const std::string& hubUrl,
                           const std::string& message) {
    if (!m_initialized.load()) return;

    Client* client;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        client = findClient(hubUrl);
        if (!client) return;
    }
    // m_mutex released — safe to call into dcpp (avoids ABBA deadlock
    // with NmdcHub::cs held by the hub socket thread)
    client->hubMessage(message);
}

void DCBridge::sendPM(const std::string& hubUrl,
                      const std::string& nick,
                      const std::string& message) {
    if (!m_initialized.load()) return;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto* client = findClient(hubUrl);
        if (!client) return;
    }
    // m_mutex released — safe to call into dcpp (avoids ABBA deadlock
    // with NmdcHub::cs / ClientManager::cs held by the hub socket thread)
    UserPtr user = ClientManager::getInstance()->findUser(nick, hubUrl);
    if (user) {
        HintedUser hu(user, hubUrl);
        ClientManager::getInstance()->privateMessage(hu, message, false);
    }
}

std::vector<std::string> DCBridge::getChatHistory(
        const std::string& hubUrl, int maxLines) {
    std::vector<std::string> result;
    if (!m_initialized.load()) return result;

    std::lock_guard<std::mutex> lock(m_mutex);
    auto* hd = findHub(hubUrl);
    if (!hd) return result;

    int start = 0;
    if (maxLines > 0 && static_cast<int>(hd->chatHistory.size()) > maxLines) {
        start = static_cast<int>(hd->chatHistory.size()) - maxLines;
    }
    for (int i = start; i < static_cast<int>(hd->chatHistory.size()); ++i) {
        result.push_back(hd->chatHistory[i]);
    }
    return result;
}

// =========================================================================
// Users
// =========================================================================

std::vector<UserInfo> DCBridge::getHubUsers(const std::string& hubUrl) {
    std::vector<UserInfo> result;
    if (!m_initialized.load()) return result;

    std::lock_guard<std::mutex> lock(m_mutex);
    auto* hd = findHub(hubUrl);
    if (!hd) return result;

    result.reserve(hd->users.size());
    for (auto& [nick, ui] : hd->users) {
        result.push_back(ui);
    }
    return result;
}

UserInfo DCBridge::getUserInfo(const std::string& nick,
                               const std::string& hubUrl) {
    UserInfo ui;
    ui.nick = nick;
    if (!m_initialized.load()) return ui;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto* client = findClient(hubUrl);
        if (!client) return ui;
    }

    // m_mutex released — safe to call ClientManager (avoids ABBA deadlock)
    UserPtr user = ClientManager::getInstance()->findUser(nick, hubUrl);
    if (user) {
        Identity id = ClientManager::getInstance()->getOnlineUserIdentity(user);
        ui.description = id.getDescription();
        ui.connection = id.getConnection();
        ui.email = id.getEmail();
        ui.shareSize = id.getBytesShared();
        ui.isOp = id.isOp();
        ui.isBot = id.isBot();
        ui.cid = user->getCID().toBase32();
    }
    return ui;
}

// =========================================================================
// Search
// =========================================================================

bool DCBridge::search(const std::string& query, int fileType,
                      int sizeMode, int64_t size,
                      const std::string& hubUrl) {
    if (!m_initialized.load()) return false;

    if (!hubUrl.empty()) {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!findClient(hubUrl)) return false;
    }

    // m_mutex released — safe to call SearchManager (avoids ABBA deadlock)
    auto sm = SearchManager::getInstance();
    auto token = Util::toString(Util::rand());

    if (hubUrl.empty()) {
        // Search all hubs
        sm->search(query, size,
                   static_cast<SearchManager::TypeModes>(fileType),
                   static_cast<SearchManager::SizeModes>(sizeMode),
                   token, nullptr);
    } else {
        // Search specific hub
        StringList hubs;
        hubs.push_back(hubUrl);
        sm->search(hubs, query, size,
                   static_cast<SearchManager::TypeModes>(fileType),
                   static_cast<SearchManager::SizeModes>(sizeMode),
                   token, StringList(), nullptr);
    }
    return true;
}

std::vector<SearchResultInfo> DCBridge::getSearchResults(
        const std::string& hubUrl) {
    std::vector<SearchResultInfo> result;
    if (!m_initialized.load()) return result;

    std::lock_guard<std::mutex> lock(m_mutex);

    if (hubUrl.empty()) {
        // Return results from all hubs
        for (auto& [url, data] : m_hubs) {
            result.insert(result.end(),
                          data.searchResults.begin(),
                          data.searchResults.end());
        }
    } else {
        auto* hd = findHub(hubUrl);
        if (hd) {
            result = hd->searchResults;
        }
    }
    return result;
}

void DCBridge::clearSearchResults(const std::string& hubUrl) {
    if (!m_initialized.load()) return;

    std::lock_guard<std::mutex> lock(m_mutex);

    if (hubUrl.empty()) {
        for (auto& [url, data] : m_hubs) {
            data.searchResults.clear();
        }
    } else {
        auto* hd = findHub(hubUrl);
        if (hd) {
            hd->searchResults.clear();
        }
    }
}

// =========================================================================
// Download queue
// =========================================================================

bool DCBridge::addToQueue(const std::string& directory,
                          const std::string& name,
                          int64_t size,
                          const std::string& tth) {
    if (!m_initialized.load()) return false;

    try {
        std::string target = directory;
        if (!target.empty() && target.back() != '/') target += '/';
        target += name;

        QueueManager::getInstance()->add(target, size,
            TTHValue(tth), HintedUser(),
            QueueItem::FLAG_NORMAL);
        return true;
    } catch (const Exception& e) {
        return false;
    }
}

bool DCBridge::addMagnet(const std::string& magnetLink,
                         const std::string& downloadDir) {
    if (!m_initialized.load()) return false;

    // Parse magnet link
    std::string name, tth;
    int64_t size = 0;

    // Extract from magnet:?xt=urn:tree:tiger:TTH&xl=SIZE&dn=NAME
    auto xtPos = magnetLink.find("xt=urn:tree:tiger:");
    if (xtPos == std::string::npos) return false;
    tth = magnetLink.substr(xtPos + 18, 39);

    auto xlPos = magnetLink.find("xl=");
    if (xlPos != std::string::npos) {
        auto end = magnetLink.find('&', xlPos);
        size = Util::toInt64(magnetLink.substr(xlPos + 3,
            end == std::string::npos ? std::string::npos : end - xlPos - 3));
    }

    auto dnPos = magnetLink.find("dn=");
    if (dnPos != std::string::npos) {
        auto end = magnetLink.find('&', dnPos);
        name = magnetLink.substr(dnPos + 3,
            end == std::string::npos ? std::string::npos : end - dnPos - 3);
        // URL decode basic escapes
        // (full decode would be more complex, this handles common cases)
    }

    if (name.empty()) name = tth;

    std::string dir = downloadDir.empty()
        ? SETTING(DOWNLOAD_DIRECTORY)
        : downloadDir;

    return addToQueue(dir, name, size, tth);
}

void DCBridge::removeFromQueue(const std::string& target) {
    if (!m_initialized.load()) return;
    try {
        QueueManager::getInstance()->remove(target);
    } catch (const Exception&) {}
}

void DCBridge::moveQueueItem(const std::string& source,
                             const std::string& target) {
    if (!m_initialized.load()) return;
    try {
        QueueManager::getInstance()->move(source, target);
    } catch (const Exception&) {}
}

void DCBridge::setPriority(const std::string& target, int priority) {
    if (!m_initialized.load()) return;
    try {
        QueueManager::getInstance()->setPriority(
            target,
            static_cast<QueueItem::Priority>(priority));
    } catch (const Exception&) {}
}

std::vector<QueueItemInfo> DCBridge::listQueue() {
    std::vector<QueueItemInfo> result;
    if (!m_initialized.load()) return result;

    const QueueItem::StringMap& ll = QueueManager::getInstance()->lockQueue();
    for (const auto& item : ll) {
        QueueItem* qi = item.second;
        QueueItemInfo info;
        info.target = qi->getTarget();
        info.filename = qi->getTargetFileName();
        info.size = qi->getSize();
        info.downloadedBytes = qi->getDownloadedBytes();
        info.tth = qi->getTTH().toBase32();
        info.priority = static_cast<int>(qi->getPriority());
        info.sources = static_cast<int>(qi->getSources().size());
        info.onlineSources = qi->countOnlineUsers();
        info.status = qi->isFinished() ? 2 : (qi->isRunning() ? 1 : 0);
        result.push_back(std::move(info));
    }
    QueueManager::getInstance()->unlockQueue();

    return result;
}

void DCBridge::clearQueue() {
    if (!m_initialized.load()) return;
    // Collect all targets first, then remove outside the lock
    auto* qm = QueueManager::getInstance();
    std::vector<std::string> targets;
    const QueueItem::StringMap& ll = qm->lockQueue();
    for (const auto& item : ll) {
        targets.push_back(*(item.first));
    }
    qm->unlockQueue();
    for (const auto& t : targets) {
        qm->remove(t);
    }
}

void DCBridge::matchAllLists() {
    if (!m_initialized.load()) return;

    // Match all downloaded file lists against the queue
    auto dir = Util::getListPath();
    // TODO: iterate file lists and match
}

// =========================================================================
// File lists
// =========================================================================

bool DCBridge::requestFileList(const std::string& hubUrl,
                               const std::string& nick,
                               bool matchQueue) {
    if (!m_initialized.load()) return false;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto* client = findClient(hubUrl);
        if (!client) return false;
    }

    // m_mutex released — safe to call ClientManager/QueueManager
    UserPtr user = ClientManager::getInstance()->findUser(nick, hubUrl);
    if (user) {
        try {
            QueueManager::getInstance()->addList(
                HintedUser(user, hubUrl),
                matchQueue ? QueueItem::FLAG_MATCH_QUEUE : 0,
                "");
            return true;
        } catch (const Exception&) {
            return false;
        }
    }
    return false;
}

std::vector<std::string> DCBridge::listLocalFileLists() {
    std::vector<std::string> result;
    if (!m_initialized.load()) return result;

    auto listPath = Util::getListPath();
    try {
        for (auto& entry : std::filesystem::directory_iterator(listPath)) {
            if (entry.is_regular_file()) {
                result.push_back(entry.path().filename().string());
            }
        }
    } catch (const std::exception&) {}
    return result;
}

bool DCBridge::openFileList(const std::string& fileListId) {
    if (!m_initialized.load()) return false;

    std::lock_guard<std::mutex> lock(m_mutex);

    if (m_fileLists.count(fileListId) > 0) return true; // Already open

    auto path = Util::getListPath() + fileListId;

    // Resolve the User from the CID embedded in the filename.
    // File list names follow: [nick].[CID-base32].xml.bz2
    UserPtr user = DirectoryListing::getUserFromFilename(fileListId);
    if (!user) {
        fprintf(stderr, "DCBridge::openFileList: could not resolve user "
                        "from filename '%s'\n", fileListId.c_str());
        return false;
    }

    // Get a hub URL hint for the user (needed for download connections)
    std::string hubHint;
    auto hubs = ClientManager::getInstance()->getHubUrls(user->getCID());
    if (!hubs.empty()) {
        hubHint = hubs.front();
    }

    try {
        auto* listing = new DirectoryListing(HintedUser(user, hubHint));
        listing->loadFile(path);
        m_fileLists[fileListId] = listing;
        return true;
    } catch (const Exception& e) {
        fprintf(stderr, "DCBridge::openFileList: %s: %s\n",
                path.c_str(), e.getError().c_str());
        return false;
    }
}

std::vector<FileListEntry> DCBridge::browseFileList(
        const std::string& fileListId,
        const std::string& directory) {
    std::vector<FileListEntry> result;
    if (!m_initialized.load()) return result;

    std::lock_guard<std::mutex> lock(m_mutex);

    auto it = m_fileLists.find(fileListId);
    if (it == m_fileLists.end()) return result;

    auto* listing = it->second;
    auto* dir = listing->getRoot();

    // Navigate to requested directory
    if (directory != "/" && !directory.empty()) {
        StringTokenizer<string> st(directory, '/');
        for (auto& tok : st.getTokens()) {
            if (tok.empty()) continue;
            bool found = false;
            for (auto d : dir->directories) {
                if (d->getName() == tok) {
                    dir = d;
                    found = true;
                    break;
                }
            }
            if (!found) return result;
        }
    }

    // List directories
    for (auto d : dir->directories) {
        FileListEntry entry;
        entry.name = d->getName();
        entry.isDirectory = true;
        entry.size = d->getTotalSize();
        result.push_back(std::move(entry));
    }

    // List files
    for (auto& f : dir->files) {
        FileListEntry entry;
        entry.name = f->getName();
        entry.size = f->getSize();
        entry.tth = f->getTTH().toBase32();
        entry.isDirectory = false;
        result.push_back(std::move(entry));
    }
    return result;
}

bool DCBridge::downloadFileFromList(const std::string& fileListId,
                                    const std::string& filePath,
                                    const std::string& downloadTo) {
    if (!m_initialized.load()) return false;

    // Extract everything we need from the listing while holding m_mutex,
    // then release it before calling into QueueManager (which fires
    // synchronous callbacks through BridgeListeners/SWIG directors).
    // Holding m_mutex during those callbacks risks ABBA deadlock with
    // the GIL when a concurrent C++ thread also fires a callback.
    int64_t fileSize = 0;
    TTHValue fileTTH;
    HintedUser hintedUser;
    std::string target;

    {
        std::lock_guard<std::mutex> lock(m_mutex);

        auto it = m_fileLists.find(fileListId);
        if (it == m_fileLists.end()) return false;

        auto* listing = it->second;

        // Split filePath into directory and filename parts (uses forward slash)
        std::string directory = Util::getFilePath(filePath, '/');
        std::string fname = Util::getFileName(filePath, '/');
        if (fname.empty()) return false;

        // Navigate to the directory containing the file
        auto* dir = listing->getRoot();
        if (!directory.empty() && directory != "/") {
            StringTokenizer<std::string> st(directory, '/');
            for (auto& tok : st.getTokens()) {
                if (tok.empty()) continue;
                bool found = false;
                for (auto d : dir->directories) {
                    if (d->getName() == tok) {
                        dir = d;
                        found = true;
                        break;
                    }
                }
                if (!found) return false;
            }
        }

        // Find the file in the directory
        DirectoryListing::File* filePtr = nullptr;
        for (auto f : dir->files) {
            if (f->getName() == fname) {
                filePtr = f;
                break;
            }
        }
        if (!filePtr) return false;

        // Extract the data we need for QueueManager::add()
        fileSize = filePtr->getSize();
        fileTTH = filePtr->getTTH();
        hintedUser = listing->getUser();

        if (!hintedUser.user) {
            fprintf(stderr, "DCBridge::downloadFileFromList: listing has null "
                            "user for '%s'\n", fileListId.c_str());
            return false;
        }

        // Build download target path
        target = downloadTo.empty()
            ? SETTING(DOWNLOAD_DIRECTORY)
            : downloadTo;
        if (!target.empty() && target.back() == PATH_SEPARATOR)
            target += fname;
        else if (!target.empty() && target.back() != PATH_SEPARATOR
                 && target.find('.') == std::string::npos)
            target += PATH_SEPARATOR + fname;
    }
    // m_mutex released — safe to call into dcpp (avoids ABBA deadlock
    // between m_mutex and dcpp internal locks / GIL)

    try {
        QueueManager::getInstance()->add(target, fileSize, fileTTH, hintedUser, 0);
    } catch (const Exception&) {
        return false;
    }
    return true;
}

bool DCBridge::downloadDirFromList(const std::string& fileListId,
                                   const std::string& dirPath,
                                   const std::string& downloadTo) {
    if (!m_initialized.load()) return false;

    std::lock_guard<std::mutex> lock(m_mutex);

    auto it = m_fileLists.find(fileListId);
    if (it == m_fileLists.end()) return false;

    auto* listing = it->second;

    if (!listing->getUser().user) {
        fprintf(stderr, "DCBridge::downloadDirFromList: listing has null "
                        "user for '%s'\n", fileListId.c_str());
        return false;
    }

    // Navigate to the requested directory
    DirectoryListing::Directory* dir = nullptr;
    if (dirPath.empty() || dirPath == "/") {
        dir = listing->getRoot();
    } else {
        dir = listing->getRoot();
        StringTokenizer<std::string> st(dirPath, '/');
        for (auto& tok : st.getTokens()) {
            if (tok.empty()) continue;
            bool found = false;
            for (auto d : dir->directories) {
                if (d->getName() == tok) {
                    dir = d;
                    found = true;
                    break;
                }
            }
            if (!found) return false;
        }
    }

    std::string target = downloadTo.empty()
        ? SETTING(DOWNLOAD_DIRECTORY)
        : downloadTo;

    try {
        listing->download(dir, target, false);
    } catch (const Exception&) {
        return false;
    }
    return true;
}

void DCBridge::closeFileList(const std::string& fileListId) {
    std::lock_guard<std::mutex> lock(m_mutex);

    auto it = m_fileLists.find(fileListId);
    if (it != m_fileLists.end()) {
        delete it->second;
        m_fileLists.erase(it);
    }
}

void DCBridge::closeAllFileLists() {
    std::lock_guard<std::mutex> lock(m_mutex);

    for (auto& [id, listing] : m_fileLists) {
        delete listing;
    }
    m_fileLists.clear();
}

// =========================================================================
// Sharing
// =========================================================================

bool DCBridge::addShareDir(const std::string& realPath,
                           const std::string& virtualName) {
    if (!m_initialized.load()) return false;

    // ShareManager::addDirectory() does not normalise the trailing
    // separator (unlike ShareManager::load()), so paths from e.g.
    // tempfile.mkdtemp() that lack a trailing '/' cause buildTree()
    // to construct malformed file paths (missing separator) and
    // silently skip every file.
    std::string path = realPath;
    if (!path.empty() && path.back() != PATH_SEPARATOR)
        path += PATH_SEPARATOR;

    try {
        ShareManager::getInstance()->addDirectory(path, virtualName);
        return true;
    } catch (const Exception&) {
        return false;
    }
}

bool DCBridge::removeShareDir(const std::string& realPath) {
    if (!m_initialized.load()) return false;
    try {
        ShareManager::getInstance()->removeDirectory(realPath);
        return true;
    } catch (const Exception&) {
        return false;
    }
}

bool DCBridge::renameShareDir(const std::string& realPath,
                              const std::string& newVirtName) {
    if (!m_initialized.load()) return false;
    try {
        ShareManager::getInstance()->renameDirectory(realPath, newVirtName);
        return true;
    } catch (const Exception&) {
        return false;
    }
}

std::vector<ShareDirInfo> DCBridge::listShare() {
    std::vector<ShareDirInfo> result;
    if (!m_initialized.load()) return result;

    auto dirs = ShareManager::getInstance()->getDirectories();
    for (auto& [virt, real] : dirs) {
        ShareDirInfo sdi;
        sdi.realPath = real;
        sdi.virtualName = virt;
        result.push_back(std::move(sdi));
    }
    return result;
}

void DCBridge::refreshShare() {
    if (!m_initialized.load()) return;
    ShareManager::getInstance()->setDirty();
    ShareManager::getInstance()->refresh(true, true, false);
}

int64_t DCBridge::getShareSize() {
    if (!m_initialized.load()) return 0;
    return ShareManager::getInstance()->getShareSize();
}

int64_t DCBridge::getSharedFileCount() {
    if (!m_initialized.load()) return 0;
    return ShareManager::getInstance()->getSharedFiles();
}

// =========================================================================
// Transfers
// =========================================================================

TransferStats DCBridge::getTransferStats() {
    TransferStats stats;
    if (!m_initialized.load()) return stats;

    stats.downloadSpeed = DownloadManager::getInstance()->getRunningAverage();
    stats.uploadSpeed = UploadManager::getInstance()->getRunningAverage();
    stats.totalDownloaded = SETTING(TOTAL_DOWNLOAD);
    stats.totalUploaded = SETTING(TOTAL_UPLOAD);
    stats.downloadCount = DownloadManager::getInstance()->getDownloadCount();
    stats.uploadCount = UploadManager::getInstance()->getUploadCount();
    return stats;
}

// =========================================================================
// Hashing
// =========================================================================

HashStatus DCBridge::getHashStatus() {
    HashStatus hs;
    if (!m_initialized.load()) return hs;

    std::string file;
    uint64_t bytesLeft = 0;
    size_t filesLeft = 0;
    HashManager::getInstance()->getStats(file, bytesLeft, filesLeft);
    hs.currentFile = file;
    hs.bytesLeft = bytesLeft;
    hs.filesLeft = filesLeft;
    return hs;
}

void DCBridge::pauseHashing(bool pause) {
    if (!m_initialized.load()) return;
    if (pause) {
        HashManager::getInstance()->pauseHashing();
    } else {
        HashManager::getInstance()->resumeHashing();
    }
}

// =========================================================================
// Settings
// =========================================================================

std::string DCBridge::getSetting(const std::string& name) {
    if (!m_initialized.load()) return "";

    auto* sm = SettingsManager::getInstance();

    // Resolve setting name → enum index + type.
    int n = 0;
    SettingsManager::Types type{};
    if (!sm->getType(name.c_str(), n, type))
        return "";  // unknown setting name

    // Read with useDefault=true so defaults (e.g. DownloadDirectory) are
    // returned even when the user hasn't explicitly overridden them.
    if (type == SettingsManager::TYPE_STRING)
        return sm->get(static_cast<SettingsManager::StrSetting>(n), true);
    else if (type == SettingsManager::TYPE_INT)
        return std::to_string(sm->get(static_cast<SettingsManager::IntSetting>(n), true));
    else if (type == SettingsManager::TYPE_INT64)
        return std::to_string(sm->get(static_cast<SettingsManager::Int64Setting>(n), true));

    return "";
}

void DCBridge::setSetting(const std::string& name,
                          const std::string& value) {
    if (!m_initialized.load()) return;

    auto* sm = SettingsManager::getInstance();

    int n = 0;
    SettingsManager::Types type{};
    if (!sm->getType(name.c_str(), n, type))
        return;  // unknown setting name

    if (type == SettingsManager::TYPE_STRING)
        sm->set(static_cast<SettingsManager::StrSetting>(n), value);
    else if (type == SettingsManager::TYPE_INT)
        sm->set(static_cast<SettingsManager::IntSetting>(n), std::atoi(value.c_str()));
    else if (type == SettingsManager::TYPE_INT64)
        sm->set(static_cast<SettingsManager::Int64Setting>(n),
                static_cast<int64_t>(std::atoll(value.c_str())));

    // Save to disk so changes persist
    sm->save();
}

void DCBridge::reloadConfig() {
    if (!m_initialized.load()) return;
    SettingsManager::getInstance()->load();
}

// =========================================================================
// Version
// =========================================================================

std::string DCBridge::getVersion() {
    return DCVERSIONSTRING;
}

// =========================================================================
// Networking setup
// =========================================================================

void DCBridge::startNetworking() {
    ConnectivityManager::getInstance()->setup(true);
    ClientManager::getInstance()->infoUpdated();
}

// =========================================================================
// Internal helpers
// =========================================================================

DCBridge::HubData* DCBridge::findHub(const std::string& url) {
    auto it = m_hubs.find(url);
    return (it != m_hubs.end()) ? &it->second : nullptr;
}

dcpp::Client* DCBridge::findClient(const std::string& url) {
    auto* hd = findHub(url);
    return hd ? hd->client : nullptr;
}

} // namespace eiskaltdcpp_py
