/*
 * bridge_listeners.cpp — Implementation of listener helper methods
 *                        that need access to DCBridge internals.
 */

#include "bridge_listeners.h"
#include "bridge.h"

namespace eiskaltdcpp_py {

void BridgeListeners::stashChat(const std::string& hubUrl,
                                const std::string& nick,
                                const std::string& text) {
    std::lock_guard<std::mutex> lk(bridge_.m_mutex);
    auto* hd = bridge_.findHub(hubUrl);
    if (!hd) return;

    std::string formatted;
    if (!nick.empty()) {
        formatted = "<" + nick + "> " + text;
    } else {
        formatted = text;
    }

    hd->chatHistory.push_back(formatted);

    // Limit history size
    static const size_t MAX_HISTORY = 500;
    while (hd->chatHistory.size() > MAX_HISTORY) {
        hd->chatHistory.pop_front();
    }
}

void BridgeListeners::stashSearchResult(const SearchResultInfo& info) {
    std::lock_guard<std::mutex> lk(bridge_.m_mutex);

    // Store in the matching hub, or the first hub if no match
    auto* hd = bridge_.findHub(info.hubUrl);
    if (hd) {
        hd->searchResults.push_back(info);
    } else if (!bridge_.m_hubs.empty()) {
        bridge_.m_hubs.begin()->second.searchResults.push_back(info);
    }
}

void BridgeListeners::stashUserUpdate(const std::string& hubUrl,
                                       const dcpp::OnlineUser& ou) {
    std::lock_guard<std::mutex> lk(bridge_.m_mutex);
    auto* hd = bridge_.findHub(hubUrl);
    if (!hd) return;
    hd->users[ou.getIdentity().getNick()] = userFromOnlineUser(ou);
}

void BridgeListeners::stashUserRemove(const std::string& hubUrl,
                                       const std::string& nick) {
    std::lock_guard<std::mutex> lk(bridge_.m_mutex);
    auto* hd = bridge_.findHub(hubUrl);
    if (!hd) return;
    hd->users.erase(nick);
}

void BridgeListeners::clearHubUsers(const std::string& hubUrl) {
    std::lock_guard<std::mutex> lk(bridge_.m_mutex);
    auto* hd = bridge_.findHub(hubUrl);
    if (!hd) return;
    hd->users.clear();
}

void BridgeListeners::refreshHubCache(const std::string& hubUrl,
                                       dcpp::Client* c) {
    if (!c) return;

    // Read all Client* accessors HERE on the socket thread where it's safe.
    // Some of these (getUserCount) acquire NmdcHub::cs, which is recursive,
    // so re-acquiring it from a callback already under cs is fine.
    HubInfo info;
    info.url        = hubUrl;
    info.name       = c->getHubName();
    info.description = c->getHubDescription();
    info.userCount  = static_cast<int>(c->getUserCount());
    info.sharedBytes = c->getAvailable();
    info.connected  = c->isConnected();
    info.isOp       = c->isOp();
    info.isSecure   = c->isSecure();
    info.isTrusted  = c->isTrusted();
    info.cipherName = c->getCipherName();

    // Now store the snapshot under bridge_.m_mutex.
    std::lock_guard<std::mutex> lk(bridge_.m_mutex);
    auto* hd = bridge_.findHub(hubUrl);
    if (!hd) return;
    hd->cachedInfo = std::move(info);
}

void BridgeListeners::markHubDisconnected(const std::string& hubUrl) {
    std::lock_guard<std::mutex> lk(bridge_.m_mutex);
    auto* hd = bridge_.findHub(hubUrl);
    if (!hd) return;
    hd->cachedInfo.connected = false;
}

} // namespace eiskaltdcpp_py
