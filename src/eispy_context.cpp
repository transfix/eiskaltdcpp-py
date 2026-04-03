/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * Copyright (C) 2026 Verlihub Team
 * Licensed under GPL-3.0-or-later
 *
 * eispy_context.cpp — EisPyContext implementation.
 *
 * Replaces bridge.cpp.  Keeps all orchestration logic (hub caching,
 * listener multiplexing, Lua scripting, file lists, lifecycle).
 * Removes simple pass-throughs now handled by direct SWIG manager access.
 */

#include "eispy_context.h"
#include "bridge_listeners.h"
#include "listener_adapters.h"
#include "callbacks.h"
#include "dcpp_compat.h"  // must precede dcpp headers (provides STL + using decls)

#include <dcpp/DCPlusPlus.h>
#include <dcpp/DCContext.h>
#include <dcpp/Util.h>
#include <dcpp/BufferedSocket.h>
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

#ifndef DCVERSIONSTRING
#define DCVERSIONSTRING "2.5.0"
#endif

static const std::string eispyNMDCTag = "eispy V:" DCVERSIONSTRING;
static const std::string eispyADCTag  = "eispy " DCVERSIONSTRING;

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <iostream>

#ifdef _WIN32
#include <process.h>
#include <windows.h>
#else
#include <dlfcn.h>
#include <pwd.h>
#include <unistd.h>
#endif

struct lua_State;  // opaque forward declaration

using namespace dcpp;

namespace eiskaltdcpp_py {

// =========================================================================
// Runtime Lua scripting initialization
// =========================================================================

using luaL_newstate_t  = lua_State* (*)();
using luaL_openlibs_t  = void (*)(lua_State*);
using lua_close_t      = void (*)(lua_State*);
using luaL_loadstring_t = int (*)(lua_State*, const char*);
using luaL_loadfilex_t = int (*)(lua_State*, const char*, const char*);
using lua_pcallk_t     = int (*)(lua_State*, int, int, int, int, void*);
using lua_tolstring_t  = const char* (*)(lua_State*, int, size_t*);
using lua_settop_t     = void (*)(lua_State*, int);

static lua_close_t      s_lua_close = nullptr;
static luaL_loadstring_t s_luaL_loadstring = nullptr;
static luaL_loadfilex_t  s_luaL_loadfilex = nullptr;
static lua_pcallk_t      s_lua_pcallk = nullptr;
static lua_tolstring_t   s_lua_tolstring = nullptr;
static lua_settop_t      s_lua_settop = nullptr;

#if defined(LUA_SCRIPT) && !defined(_WIN32)
static lua_State** resolveLuaStatePtr() {
    void* sym = dlsym(RTLD_DEFAULT, "_ZN4dcpp14ScriptInstance1LE");
    return reinterpret_cast<lua_State**>(sym);
}
#endif

static void initLuaScriptingIfPresent() {
#if defined(LUA_SCRIPT) && !defined(_WIN32)
    lua_State** lua_state_ptr = resolveLuaStatePtr();
    if (!lua_state_ptr)
        return;

    if (*lua_state_ptr)
        return;

    auto fn_newstate = reinterpret_cast<luaL_newstate_t>(
        dlsym(RTLD_DEFAULT, "luaL_newstate"));
    auto fn_openlibs = reinterpret_cast<luaL_openlibs_t>(
        dlsym(RTLD_DEFAULT, "luaL_openlibs"));
    s_lua_close = reinterpret_cast<lua_close_t>(
        dlsym(RTLD_DEFAULT, "lua_close"));

    if (!fn_newstate || !fn_openlibs || !s_lua_close)
        return;

    s_luaL_loadstring = reinterpret_cast<luaL_loadstring_t>(
        dlsym(RTLD_DEFAULT, "luaL_loadstring"));
    s_luaL_loadfilex = reinterpret_cast<luaL_loadfilex_t>(
        dlsym(RTLD_DEFAULT, "luaL_loadfilex"));
    s_lua_pcallk = reinterpret_cast<lua_pcallk_t>(
        dlsym(RTLD_DEFAULT, "lua_pcallk"));
    s_lua_tolstring = reinterpret_cast<lua_tolstring_t>(
        dlsym(RTLD_DEFAULT, "lua_tolstring"));
    s_lua_settop = reinterpret_cast<lua_settop_t>(
        dlsym(RTLD_DEFAULT, "lua_settop"));

    lua_State* L = fn_newstate();
    if (!L) return;
    fn_openlibs(L);

    *lua_state_ptr = L;
#endif
}

// =========================================================================
// Startup callback
// =========================================================================

static void startupCallback(void*, const std::string& msg) {
    // Could log this if desired
}

// =========================================================================
// Global dcpp lifecycle — permanent singleton
// =========================================================================
// The dcpp library uses pervasive global state (Util paths, static
// registrations, manager singletons inside DCContext).  Calling
// DCContext::shutdown() followed by dcpp::startup() corrupts memory
// because the library was not designed for restart.
//
// Solution: once started, the dcpp core lives for the process lifetime.
// EisPyContext::shutdown() only cleans up per-instance state (hubs,
// listeners, file lists).  The DCContext is never destroyed — the OS
// reclaims everything at process exit.
// =========================================================================

// Raw pointer — intentionally leaked at process exit so that
// DCContext's destructor never runs (which would double-free managers).
static dcpp::DCContext* g_dcppContext  = nullptr;
static bool             g_dcppTimerStarted{false};
static std::mutex       g_dcppMutex;

// =========================================================================
// Construction / Destruction
// =========================================================================

EisPyContext::EisPyContext() = default;

EisPyContext::~EisPyContext() {
    if (m_initialized.load()) {
        shutdown();
    }
}

// =========================================================================
// Lifecycle
// =========================================================================

// =========================================================================
// Private: resolve and create the configuration directory
// =========================================================================

std::string EisPyContext::resolveConfigDir(const std::string& configDir) {
    std::string cfgDir = configDir;
    if (cfgDir.empty()) {
        const char* home = getenv("HOME");
        if (home) {
            cfgDir = std::string(home) + "/.eiskaltdcpp-py/";
        } else {
#ifdef _WIN32
            const char* appdata = getenv("LOCALAPPDATA");
            if (appdata)
                cfgDir = std::string(appdata) + "\\eiskaltdcpp-py\\";
            else
                cfgDir = "C:\\Temp\\.eiskaltdcpp-py\\";
#else
            cfgDir = "/tmp/.eiskaltdcpp-py/";
#endif
        }
    }

    if (!cfgDir.empty() && cfgDir.back() != '/' && cfgDir.back() != '\\') {
        cfgDir += '/';
    }
    return cfgDir;
}

// =========================================================================
// Private: apply default settings after startup
// =========================================================================

void EisPyContext::applyDefaults(const std::string& cfgDir) {
    // Ensure a nick is set
    {
        auto* sm = m_context->getSettingsManager();
        std::string currentNick = sm->get(SettingsManager::NICK, true);
        if (currentNick.empty()) {
            std::string defaultNick = "eispy-" + std::to_string(getpid());
            sm->set(SettingsManager::NICK, defaultNick);
        }
    }

    // Set a default description
    {
        auto* sm = m_context->getSettingsManager();
        std::string currentDesc = sm->get(SettingsManager::DESCRIPTION, true);
        if (currentDesc.empty()) {
            std::string user, host;
#ifdef _WIN32
            char nameBuf[256];
            DWORD nameSz = sizeof(nameBuf);
            if (GetUserNameA(nameBuf, &nameSz))
                user = nameBuf;
            nameSz = sizeof(nameBuf);
            if (GetComputerNameA(nameBuf, &nameSz))
                host = nameBuf;
#else
            if (auto* pw = getpwuid(getuid()))
                user = pw->pw_name;
            char hostBuf[256];
            if (gethostname(hostBuf, sizeof(hostBuf)) == 0) {
                hostBuf[sizeof(hostBuf) - 1] = '\0';
                host = hostBuf;
            }
#endif
            if (!user.empty() && !host.empty())
                sm->set(SettingsManager::DESCRIPTION, user + "@" + host);
            else if (!user.empty())
                sm->set(SettingsManager::DESCRIPTION, user);
        }
    }

    // Ensure a download directory is set.
    // On Windows, Util::initialize() may leave PATH_DOWNLOADS empty
    // (the default-path code is inside a non-Windows #else branch in
    // dcpp/Util.cpp).  Fall back to the config directory itself.
    {
        auto* sm = m_context->getSettingsManager();
        std::string dlDir = sm->get(SettingsManager::DOWNLOAD_DIRECTORY, true);
        if (dlDir.empty()) {
            sm->set(SettingsManager::DOWNLOAD_DIRECTORY, cfgDir + "Downloads/");
        }
    }
}

// =========================================================================
// Lifecycle
// =========================================================================

bool EisPyContext::initialize(const std::string& configDir) {
    if (m_initialized.load()) {
        return true;
    }

    std::lock_guard<std::mutex> lock(m_mutex);

    std::string cfgDir = resolveConfigDir(configDir);
    m_configDir = cfgDir;

    try {
        std::filesystem::create_directories(cfgDir);
    } catch (const std::exception& e) {
        return false;
    }

    // --- Global dcpp lifecycle (permanent singleton) ---
    {
        std::lock_guard<std::mutex> glock(g_dcppMutex);

        if (!g_dcppContext) {
            // First-ever init — perform the real dcpp startup
            Util::PathsMap pathOverrides;
            pathOverrides[Util::PATH_USER_CONFIG] = cfgDir;
            pathOverrides[Util::PATH_USER_LOCAL] = cfgDir;
            Util::initialize(pathOverrides);

            try {
                g_dcppContext = dcpp::startup(startupCallback, nullptr).release();
            } catch (const std::exception& e) {
                throw std::runtime_error(
                    std::string("dcpp::startup() failed: ") + e.what());
            } catch (...) {
                throw std::runtime_error(
                    "dcpp::startup() failed with unknown exception");
            }
        }

        m_context = g_dcppContext;

        if (!g_dcppTimerStarted) {
            applyDefaults(cfgDir);
            initLuaScriptingIfPresent();
            try {
                dcpp::getContext()->getTimerManager()->start();
            } catch (const std::exception& e) {
                throw std::runtime_error(
                    std::string("TimerManager::start() failed: ") + e.what());
            }
            g_dcppTimerStarted = true;
        }
    }

    m_listeners = std::make_unique<BridgeListeners>(*this);
    m_listeners->subscribeGlobal();

    m_initialized.store(true);
    return true;
}

bool EisPyContext::initializeMinimal(const std::string& configDir) {
    if (m_initialized.load()) {
        return true;
    }

    std::lock_guard<std::mutex> lock(m_mutex);

    std::string cfgDir = resolveConfigDir(configDir);
    m_configDir = cfgDir;

    try {
        std::filesystem::create_directories(cfgDir);
    } catch (const std::exception& e) {
        return false;
    }

    // Ensure Util paths are set (first caller wins via s_utilInitDone guard).
    {
        std::lock_guard<std::mutex> glock(g_dcppMutex);
        Util::PathsMap pathOverrides;
        pathOverrides[Util::PATH_USER_CONFIG] = cfgDir;
        pathOverrides[Util::PATH_USER_LOCAL] = cfgDir;
        Util::initialize(pathOverrides);
    }

    // Create a private (non-global) DCContext in minimal mode.
    // This avoids poisoning the global singleton that full initialize()
    // depends on for later tests / production use.
    m_ownedContext = std::make_unique<dcpp::DCContext>();
    m_ownedContext->startupMinimal();
    m_context = m_ownedContext.get();

    applyDefaults(cfgDir);

    m_initialized.store(true);
    return true;
}

void EisPyContext::shutdown() {
    if (!m_initialized.load()) {
        return;
    }

    // Detach per-hub listeners FIRST
    if (m_listeners) {
        std::lock_guard<std::mutex> lock(m_mutex);
        for (auto& [url, data] : m_hubs) {
            if (data.client) {
                m_listeners->detach(data.client);
            }
        }
    }

    if (m_listeners) {
        m_listeners->unsubscribeGlobal();
        m_listeners->setCallback(nullptr);
    }

    std::vector<Client*> clients;
    {
        std::lock_guard<std::mutex> lock(m_mutex);

        for (auto& [id, listing] : m_fileLists) {
            delete listing;
        }
        m_fileLists.clear();

        for (auto& [url, data] : m_hubs) {
            if (data.client) {
                clients.push_back(data.client);
            }
        }
        m_hubs.clear();
    }

    for (auto* client : clients) {
        client->disconnect(true);
        dcpp::getContext()->getClientManager()->putClient(client);
    }

    m_listeners.reset();
    m_context = nullptr;

    // If this instance owns a minimal DCContext, shut it down and release.
    if (m_ownedContext) {
        m_ownedContext->shutdown();
        m_ownedContext.reset();
    }

    // Note: we intentionally do NOT call DCContext::shutdown() on the
    // global singleton.
    // The dcpp core is a permanent singleton that lives for the process
    // lifetime.  Calling DCContext::shutdown() destroys all managers
    // and calls Util::uninitialize(), after which dcpp::startup()
    // cannot safely be called again (heap corruption).
    //
    // Per-instance state (hubs, listeners, file lists) is cleaned up
    // above.  The OS reclaims dcpp resources at process exit.

    m_initialized.store(false);
}

bool EisPyContext::isInitialized() const {
    return m_initialized.load();
}

// =========================================================================
// Callbacks
// =========================================================================

void EisPyContext::setCallback(DCClientCallback* cb) {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_callback = cb;
    if (m_listeners)
        m_listeners->setCallback(cb);
}

// =========================================================================
// Hub connections
// =========================================================================

void EisPyContext::connectHub(const std::string& url,
                          const std::string& encoding) {
    if (!m_initialized.load()) return;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_hubs.count(url) > 0) return;
    }

    Client* client = getContext()->getClientManager()->getClient(url);
    if (!client) return;

    if (!encoding.empty()) {
        client->setEncoding(encoding);
    }

    if (url.compare(0, 6, "adc://") == 0 ||
        url.compare(0, 7, "adcs://") == 0)
        client->setClientId(eispyADCTag);
    else
        client->setClientId(eispyNMDCTag);

    // Create the HubData entry BEFORE connect() so that callbacks
    // from the socket thread (UserUpdated, etc.) always find the hub.
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        HubData hd;
        hd.client = client;
        hd.cachedInfo.url = url;
        m_hubs[url] = std::move(hd);
    }

    m_listeners->attach(client);
    client->connect();
}

void EisPyContext::disconnectHub(const std::string& url) {
    if (!m_initialized.load()) return;

    Client* client = nullptr;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto it = m_hubs.find(url);
        if (it == m_hubs.end()) return;
        client = it->second.client;
        m_hubs.erase(it);
    }

    if (client) {
        m_listeners->detach(client);
        client->disconnect(true);
        getContext()->getClientManager()->putClient(client);
    }
}

std::vector<HubInfo> EisPyContext::listHubs() {
    std::vector<HubInfo> result;
    if (!m_initialized.load()) return result;

    std::lock_guard<std::mutex> lock(m_mutex);
    result.reserve(m_hubs.size());
    for (auto& [url, data] : m_hubs) {
        result.push_back(data.cachedInfo);
    }
    return result;
}

bool EisPyContext::isHubConnected(const std::string& hubUrl) {
    if (!m_initialized.load()) return false;

    std::lock_guard<std::mutex> lock(m_mutex);
    auto* hd = findHub(hubUrl);
    return hd && hd->cachedInfo.connected;
}

// =========================================================================
// Chat
// =========================================================================

void EisPyContext::sendMessage(const std::string& hubUrl,
                           const std::string& message) {
    if (!m_initialized.load()) return;

    Client* client;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        client = findClient(hubUrl);
        if (!client) return;
    }
    client->hubMessage(message);
}

void EisPyContext::sendPM(const std::string& hubUrl,
                      const std::string& nick,
                      const std::string& message) {
    if (!m_initialized.load()) return;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto* client = findClient(hubUrl);
        if (!client) return;
    }
    UserPtr user = getContext()->getClientManager()->findUser(nick, hubUrl);
    if (user) {
        HintedUser hu(user, hubUrl);
        getContext()->getClientManager()->privateMessage(hu, message, false);
    }
}

std::vector<std::string> EisPyContext::getChatHistory(
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

std::vector<UserInfo> EisPyContext::getHubUsers(const std::string& hubUrl) {
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

UserInfo EisPyContext::getUserInfo(const std::string& nick,
                               const std::string& hubUrl) {
    UserInfo ui;
    ui.nick = nick;
    if (!m_initialized.load()) return ui;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto* client = findClient(hubUrl);
        if (!client) return ui;
    }

    UserPtr user = getContext()->getClientManager()->findUser(nick, hubUrl);
    if (user) {
        Identity id = getContext()->getClientManager()->getOnlineUserIdentity(user);
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

bool EisPyContext::search(const std::string& query, int fileType,
                      int sizeMode, int64_t size,
                      const std::string& hubUrl) {
    if (!m_initialized.load()) return false;

    if (!hubUrl.empty()) {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!findClient(hubUrl)) return false;
    }

    auto* sm = getContext()->getSearchManager();
    auto token = Util::toString(Util::rand());

    if (hubUrl.empty()) {
        sm->search(query, size,
                   static_cast<SearchManager::TypeModes>(fileType),
                   static_cast<SearchManager::SizeModes>(sizeMode),
                   token, nullptr);
    } else {
        StringList hubs;
        hubs.push_back(hubUrl);
        sm->search(hubs, query, size,
                   static_cast<SearchManager::TypeModes>(fileType),
                   static_cast<SearchManager::SizeModes>(sizeMode),
                   token, StringList(), nullptr);
    }
    return true;
}

std::vector<SearchResultInfo> EisPyContext::getSearchResults(
        const std::string& hubUrl) {
    std::vector<SearchResultInfo> result;
    if (!m_initialized.load()) return result;

    std::lock_guard<std::mutex> lock(m_mutex);

    if (hubUrl.empty()) {
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

void EisPyContext::clearSearchResults(const std::string& hubUrl) {
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

bool EisPyContext::addToQueue(const std::string& directory,
                          const std::string& name,
                          int64_t size,
                          const std::string& tth) {
    if (!m_initialized.load()) return false;

    try {
        std::string target = directory;
        if (!target.empty() && target.back() != '/') target += '/';
        target += name;

        getContext()->getQueueManager()->add(target, size,
            TTHValue(tth), HintedUser(),
            QueueItem::FLAG_NORMAL);
        return true;
    } catch (const Exception& e) {
        return false;
    }
}

bool EisPyContext::addMagnet(const std::string& magnetLink,
                         const std::string& downloadDir) {
    if (!m_initialized.load()) return false;

    std::string name, tth;
    int64_t size = 0;

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
    }

    if (name.empty()) name = tth;

    std::string dir = downloadDir.empty()
        ? m_context->getSettingsManager()->get(SettingsManager::DOWNLOAD_DIRECTORY, true)
        : downloadDir;

    return addToQueue(dir, name, size, tth);
}

std::vector<QueueItemInfo> EisPyContext::listQueue() {
    std::vector<QueueItemInfo> result;
    if (!m_initialized.load()) return result;

    const QueueItem::StringMap& ll = getContext()->getQueueManager()->lockQueue();
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
    getContext()->getQueueManager()->unlockQueue();

    return result;
}

void EisPyContext::clearQueue() {
    if (!m_initialized.load()) return;
    auto* qm = getContext()->getQueueManager();
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

void EisPyContext::matchAllLists() {
    if (!m_initialized.load()) return;
    // TODO: iterate file lists and match
}

// =========================================================================
// File lists
// =========================================================================

bool EisPyContext::requestFileList(const std::string& hubUrl,
                               const std::string& nick,
                               bool matchQueue) {
    if (!m_initialized.load()) return false;

    {
        std::lock_guard<std::mutex> lock(m_mutex);
        auto* client = findClient(hubUrl);
        if (!client) return false;
    }

    UserPtr user = getContext()->getClientManager()->findUser(nick, hubUrl);
    if (user) {
        try {
            getContext()->getQueueManager()->addList(
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

std::vector<std::string> EisPyContext::listLocalFileLists() {
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

bool EisPyContext::openFileList(const std::string& fileListId) {
    if (!m_initialized.load()) return false;

    std::lock_guard<std::mutex> lock(m_mutex);

    if (m_fileLists.count(fileListId) > 0) return true;

    auto path = Util::getListPath() + fileListId;

    UserPtr user = DirectoryListing::getUserFromFilename(*m_context, fileListId);
    if (!user) {
        fprintf(stderr, "EisPyContext::openFileList: could not resolve user "
                        "from filename '%s'\n", fileListId.c_str());
        return false;
    }

    std::string hubHint;
    auto hubs = getContext()->getClientManager()->getHubUrls(user->getCID());
    if (!hubs.empty()) {
        hubHint = hubs.front();
    }

    try {
        auto* listing = new DirectoryListing(*m_context, HintedUser(user, hubHint));
        listing->loadFile(path);
        m_fileLists[fileListId] = listing;
        return true;
    } catch (const Exception& e) {
        fprintf(stderr, "EisPyContext::openFileList: %s: %s\n",
                path.c_str(), e.getError().c_str());
        return false;
    }
}

std::vector<FileListEntry> EisPyContext::browseFileList(
        const std::string& fileListId,
        const std::string& directory) {
    std::vector<FileListEntry> result;
    if (!m_initialized.load()) return result;

    std::lock_guard<std::mutex> lock(m_mutex);

    auto it = m_fileLists.find(fileListId);
    if (it == m_fileLists.end()) return result;

    auto* listing = it->second;
    auto* dir = listing->getRoot();

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

    for (auto d : dir->directories) {
        FileListEntry entry;
        entry.name = d->getName();
        entry.isDirectory = true;
        entry.size = d->getTotalSize();
        result.push_back(std::move(entry));
    }

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

bool EisPyContext::downloadFileFromList(const std::string& fileListId,
                                    const std::string& filePath,
                                    const std::string& downloadTo) {
    if (!m_initialized.load()) return false;

    int64_t fileSize = 0;
    TTHValue fileTTH;
    HintedUser hintedUser;
    std::string target;

    {
        std::lock_guard<std::mutex> lock(m_mutex);

        auto it = m_fileLists.find(fileListId);
        if (it == m_fileLists.end()) return false;

        auto* listing = it->second;

        std::string directory = Util::getFilePath(filePath, '/');
        std::string fname = Util::getFileName(filePath, '/');
        if (fname.empty()) return false;

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

        DirectoryListing::File* filePtr = nullptr;
        for (auto f : dir->files) {
            if (f->getName() == fname) {
                filePtr = f;
                break;
            }
        }
        if (!filePtr) return false;

        fileSize = filePtr->getSize();
        fileTTH = filePtr->getTTH();
        hintedUser = listing->getUser();

        if (!hintedUser.user) {
            fprintf(stderr, "EisPyContext::downloadFileFromList: listing has null "
                            "user for '%s'\n", fileListId.c_str());
            return false;
        }

        target = downloadTo.empty()
            ? m_context->getSettingsManager()->get(SettingsManager::DOWNLOAD_DIRECTORY, true)
            : downloadTo;
        if (!target.empty() && target.back() == PATH_SEPARATOR)
            target += fname;
        else if (!target.empty() && target.back() != PATH_SEPARATOR
                 && target.find('.') == std::string::npos)
            target += PATH_SEPARATOR + fname;
    }

    try {
        getContext()->getQueueManager()->add(target, fileSize, fileTTH, hintedUser, 0);
    } catch (const Exception&) {
        return false;
    }
    return true;
}

bool EisPyContext::downloadDirFromList(const std::string& fileListId,
                                   const std::string& dirPath,
                                   const std::string& downloadTo) {
    if (!m_initialized.load()) return false;

    std::lock_guard<std::mutex> lock(m_mutex);

    auto it = m_fileLists.find(fileListId);
    if (it == m_fileLists.end()) return false;

    auto* listing = it->second;

    if (!listing->getUser().user) {
        fprintf(stderr, "EisPyContext::downloadDirFromList: listing has null "
                        "user for '%s'\n", fileListId.c_str());
        return false;
    }

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
        ? m_context->getSettingsManager()->get(SettingsManager::DOWNLOAD_DIRECTORY, true)
        : downloadTo;

    try {
        listing->download(dir, target, false);
    } catch (const Exception&) {
        return false;
    }
    return true;
}

void EisPyContext::closeFileList(const std::string& fileListId) {
    std::lock_guard<std::mutex> lock(m_mutex);

    auto it = m_fileLists.find(fileListId);
    if (it != m_fileLists.end()) {
        delete it->second;
        m_fileLists.erase(it);
    }
}

void EisPyContext::closeAllFileLists() {
    std::lock_guard<std::mutex> lock(m_mutex);

    for (auto& [id, listing] : m_fileLists) {
        delete listing;
    }
    m_fileLists.clear();
}

// =========================================================================
// Sharing
// =========================================================================

bool EisPyContext::addShareDir(const std::string& realPath,
                           const std::string& virtualName) {
    if (!m_initialized.load()) return false;

    std::string path = realPath;
    if (!path.empty() && path.back() != PATH_SEPARATOR)
        path += PATH_SEPARATOR;

    try {
        getContext()->getShareManager()->addDirectory(path, virtualName);
        return true;
    } catch (const Exception&) {
        return false;
    }
}

// =========================================================================
// Lua scripting
// =========================================================================

bool EisPyContext::luaIsAvailable() const {
#if defined(LUA_SCRIPT) && !defined(_WIN32)
    lua_State** lua_state_ptr = resolveLuaStatePtr();
    return (lua_state_ptr != nullptr && *lua_state_ptr != nullptr);
#else
    return false;
#endif
}

void EisPyContext::luaEval(const std::string& code) {
    if (!m_initialized.load()) throw LuaError("context not initialized");

#if defined(LUA_SCRIPT) && !defined(_WIN32)
    lua_State** lua_state_ptr = resolveLuaStatePtr();
    if (!lua_state_ptr || !*lua_state_ptr)
        throw LuaNotAvailableError();
    if (!s_luaL_loadstring || !s_lua_pcallk || !s_lua_tolstring || !s_lua_settop)
        throw LuaSymbolError();

    lua_State* L = *lua_state_ptr;

    int err = s_luaL_loadstring(L, code.c_str());
    if (err != 0) {
        std::string msg = "load error";
        const char* s = s_lua_tolstring(L, -1, nullptr);
        if (s) msg = s;
        s_lua_settop(L, 0);
        throw LuaLoadError(msg);
    }

    err = s_lua_pcallk(L, 0, 0, 0, 0, nullptr);
    if (err != 0) {
        std::string msg = "runtime error";
        const char* s = s_lua_tolstring(L, -1, nullptr);
        if (s) msg = s;
        s_lua_settop(L, 0);
        throw LuaRuntimeError(msg);
    }
#else
    throw LuaNotAvailableError();
#endif
}

void EisPyContext::luaEvalFile(const std::string& path) {
    if (!m_initialized.load()) throw LuaError("context not initialized");

#if defined(LUA_SCRIPT) && !defined(_WIN32)
    lua_State** lua_state_ptr = resolveLuaStatePtr();
    if (!lua_state_ptr || !*lua_state_ptr)
        throw LuaNotAvailableError();
    if (!s_luaL_loadfilex || !s_lua_pcallk || !s_lua_tolstring || !s_lua_settop)
        throw LuaSymbolError();

    lua_State* L = *lua_state_ptr;

    int err = s_luaL_loadfilex(L, path.c_str(), nullptr);
    if (err != 0) {
        std::string msg = "load error";
        const char* s = s_lua_tolstring(L, -1, nullptr);
        if (s) msg = s;
        s_lua_settop(L, 0);
        throw LuaLoadError(msg);
    }

    err = s_lua_pcallk(L, 0, 0, 0, 0, nullptr);
    if (err != 0) {
        std::string msg = "runtime error";
        const char* s = s_lua_tolstring(L, -1, nullptr);
        if (s) msg = s;
        s_lua_settop(L, 0);
        throw LuaRuntimeError(msg);
    }
#else
    throw LuaNotAvailableError();
#endif
}

std::string EisPyContext::luaGetScriptsPath() const {
    return m_configDir + "scripts/";
}

std::vector<std::string> EisPyContext::luaListScripts() const {
    std::vector<std::string> scripts;
    std::string scriptsDir = m_configDir + "scripts/";

    try {
        if (!std::filesystem::exists(scriptsDir))
            return scripts;
        for (const auto& entry : std::filesystem::directory_iterator(scriptsDir)) {
            if (entry.is_regular_file()) {
                auto ext = entry.path().extension().string();
                if (ext == ".lua") {
                    scripts.push_back(entry.path().filename().string());
                }
            }
        }
    } catch (...) {}

    std::sort(scripts.begin(), scripts.end());
    return scripts;
}

// =========================================================================
// Version
// =========================================================================

std::string EisPyContext::getVersion() {
    return DCVERSIONSTRING;
}

// =========================================================================
// Networking setup
// =========================================================================

void EisPyContext::startNetworking() {
    getContext()->getConnectivityManager()->setup(true);
    getContext()->getClientManager()->infoUpdated();
}

// =========================================================================
// Internal helpers
// =========================================================================

EisPyContext::HubData* EisPyContext::findHub(const std::string& url) {
    auto it = m_hubs.find(url);
    return (it != m_hubs.end()) ? &it->second : nullptr;
}

dcpp::Client* EisPyContext::findClient(const std::string& url) {
    auto* hd = findHub(url);
    return hd ? hd->client : nullptr;
}

// =========================================================================
// Per-manager listener subscription (Phase 4)
// =========================================================================

void EisPyContext::addHubListener(const std::string& hubUrl,
                                   PyClientListener* listener) {
    if (!listener) return;
    std::lock_guard<std::mutex> lk(m_mutex);
    auto* client = findClient(hubUrl);
    if (client) {
        client->addListener(listener);
    }
}

void EisPyContext::removeHubListener(const std::string& hubUrl,
                                      PyClientListener* listener) {
    if (!listener) return;
    std::lock_guard<std::mutex> lk(m_mutex);
    auto* client = findClient(hubUrl);
    if (client) {
        client->removeListener(listener);
    }
}

void EisPyContext::addClientManagerListener(PyClientManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getClientManager()->addListener(listener);
}

void EisPyContext::removeClientManagerListener(PyClientManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getClientManager()->removeListener(listener);
}

void EisPyContext::addSearchListener(PySearchManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getSearchManager()->addListener(listener);
}

void EisPyContext::removeSearchListener(PySearchManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getSearchManager()->removeListener(listener);
}

void EisPyContext::addQueueListener(PyQueueManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getQueueManager()->addListener(listener);
}

void EisPyContext::removeQueueListener(PyQueueManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getQueueManager()->removeListener(listener);
}

void EisPyContext::addDownloadListener(PyDownloadManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getDownloadManager()->addListener(listener);
}

void EisPyContext::removeDownloadListener(PyDownloadManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getDownloadManager()->removeListener(listener);
}

void EisPyContext::addUploadListener(PyUploadManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getUploadManager()->addListener(listener);
}

void EisPyContext::removeUploadListener(PyUploadManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getUploadManager()->removeListener(listener);
}

void EisPyContext::addTimerListener(PyTimerManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getTimerManager()->addListener(listener);
}

void EisPyContext::removeTimerListener(PyTimerManagerListener* listener) {
    if (!listener || !m_initialized) return;
    dcpp::getContext()->getTimerManager()->removeListener(listener);
}

} // namespace eiskaltdcpp_py
