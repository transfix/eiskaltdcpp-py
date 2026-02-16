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

} // namespace eiskaltdcpp_py
