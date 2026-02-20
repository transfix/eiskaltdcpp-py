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
    if (!m_bridge) return;

    std::lock_guard<std::mutex> lk(m_bridge->m_mutex);
    auto* hd = m_bridge->findHub(hubUrl);
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
    if (!m_bridge) return;

    std::lock_guard<std::mutex> lk(m_bridge->m_mutex);

    // Store in the matching hub, or the first hub if no match
    auto* hd = m_bridge->findHub(info.hubUrl);
    if (hd) {
        hd->searchResults.push_back(info);
    } else if (!m_bridge->m_hubs.empty()) {
        m_bridge->m_hubs.begin()->second.searchResults.push_back(info);
    }
}

void BridgeListeners::stashUserUpdate(const std::string& hubUrl,
                                       const dcpp::OnlineUser& ou) {
    if (!m_bridge) return;
    std::lock_guard<std::mutex> lk(m_bridge->m_mutex);
    auto* hd = m_bridge->findHub(hubUrl);
    if (!hd) return;
    hd->users[ou.getIdentity().getNick()] = userFromOnlineUser(ou);
}

void BridgeListeners::stashUserRemove(const std::string& hubUrl,
                                       const std::string& nick) {
    if (!m_bridge) return;
    std::lock_guard<std::mutex> lk(m_bridge->m_mutex);
    auto* hd = m_bridge->findHub(hubUrl);
    if (!hd) return;
    hd->users.erase(nick);
}

void BridgeListeners::clearHubUsers(const std::string& hubUrl) {
    if (!m_bridge) return;
    std::lock_guard<std::mutex> lk(m_bridge->m_mutex);
    auto* hd = m_bridge->findHub(hubUrl);
    if (!hd) return;
    hd->users.clear();
}

void BridgeListeners::refreshHubCache(const std::string& hubUrl,
                                       dcpp::Client* c) {
    if (!m_bridge || !c) return;

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

    // Now store the snapshot under m_mutex.
    std::lock_guard<std::mutex> lk(m_bridge->m_mutex);
    auto* hd = m_bridge->findHub(hubUrl);
    if (!hd) return;
    hd->cachedInfo = std::move(info);
}

void BridgeListeners::markHubDisconnected(const std::string& hubUrl) {
    if (!m_bridge) return;
    std::lock_guard<std::mutex> lk(m_bridge->m_mutex);
    auto* hd = m_bridge->findHub(hubUrl);
    if (!hd) return;
    hd->cachedInfo.connected = false;
}

} // namespace eiskaltdcpp_py
