/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * bridge_listeners.h — Implements dcpp listener interfaces and routes
 *                      events to our DCClientCallback.
 *
 * The dcpp core uses a Speaker/Listener observer pattern: managers inherit
 * Speaker<XyzListener> and fire events via tagged overloads of on().
 * This file provides a singleton BridgeListeners that subscribes to all
 * relevant managers and per-hub Client objects, then converts the raw dcpp
 * types into our eiskaltdcpp_py types before forwarding to the callback.
 */

#pragma once

#include "callbacks.h"
#include "types.h"
#include "dcpp_compat.h"  // must precede dcpp headers

#include <dcpp/Client.h>
#include <dcpp/ClientListener.h>
#include <dcpp/ClientManager.h>
#include <dcpp/ChatMessage.h>
#include <dcpp/CID.h>
#include <dcpp/Download.h>
#include <dcpp/DownloadManager.h>
#include <dcpp/DownloadManagerListener.h>
#include <dcpp/HashManager.h>
#include <dcpp/OnlineUser.h>
#include <dcpp/QueueItem.h>
#include <dcpp/QueueManager.h>
#include <dcpp/QueueManagerListener.h>
#include <dcpp/SearchManager.h>
#include <dcpp/SearchManagerListener.h>
#include <dcpp/SearchResult.h>
#include <dcpp/TimerManager.h>
#include <dcpp/Transfer.h>
#include <dcpp/Upload.h>
#include <dcpp/UploadManager.h>
#include <dcpp/UploadManagerListener.h>
#include <dcpp/Util.h>

#include <map>
#include <mutex>
#include <string>

// Forward declare
namespace eiskaltdcpp_py {
class DCBridge;
}

namespace eiskaltdcpp_py {

// =========================================================================
// Helper: convert dcpp types to our info structs
// =========================================================================

inline UserInfo userFromOnlineUser(const dcpp::OnlineUser& ou) {
    UserInfo ui;
    auto& id = ou.getIdentity();
    ui.nick = id.getNick();
    ui.description = id.getDescription();
    ui.connection = id.getConnection();
    ui.email = id.getEmail();
    ui.shareSize = dcpp::Util::toInt64(id.get("SS"));
    ui.isOp = id.isOp();
    ui.isBot = id.isBot();
    ui.cid = ou.getUser()->getCID().toBase32();
    return ui;
}

inline SearchResultInfo infoFromSearchResult(const dcpp::SearchResultPtr& sr) {
    SearchResultInfo sri;
    sri.file = sr->getBaseName();
    sri.size = sr->getSize();
    sri.freeSlots = sr->getFreeSlots();
    sri.totalSlots = sr->getSlots();
    sri.tth = sr->getTTH().toBase32();
    sri.hubUrl = sr->getHubURL();
    sri.hubName = sr->getHubName();
    {
        auto nicks = dcpp::ClientManager::getInstance()->getNicks(
            sr->getUser()->getCID(), sr->getHubURL());
        sri.nick = nicks.empty() ? "" : nicks[0];
    }
    sri.isDirectory = (sr->getType() == dcpp::SearchResult::TYPE_DIRECTORY);
    return sri;
}

inline TransferInfo infoFromDownload(const dcpp::Download* dl) {
    TransferInfo ti;
    ti.filename = dl->getPath();
    ti.size = dl->getSize();
    ti.pos = dl->getPos();
    ti.speed = static_cast<int64_t>(dl->getAverageSpeed());
    ti.isDownload = true;
    if (dl->getHintedUser().user) {
        auto nicks = dcpp::ClientManager::getInstance()->getNicks(dl->getHintedUser());
        ti.nick = nicks.empty() ? "" : nicks[0];
        ti.hubUrl = dl->getHintedUser().hint;
    }
    return ti;
}

inline TransferInfo infoFromUpload(const dcpp::Upload* ul) {
    TransferInfo ti;
    ti.filename = ul->getPath();
    ti.size = ul->getSize();
    ti.pos = ul->getPos();
    ti.speed = static_cast<int64_t>(ul->getAverageSpeed());
    ti.isDownload = false;
    if (ul->getHintedUser().user) {
        auto nicks = dcpp::ClientManager::getInstance()->getNicks(ul->getHintedUser());
        ti.nick = nicks.empty() ? "" : nicks[0];
        ti.hubUrl = ul->getHintedUser().hint;
    }
    return ti;
}

// =========================================================================
// BridgeListeners — singleton that implements all dcpp listener protocols
// =========================================================================

class BridgeListeners :
        public dcpp::ClientListener,
        public dcpp::SearchManagerListener,
        public dcpp::QueueManagerListener,
        public dcpp::DownloadManagerListener,
        public dcpp::UploadManagerListener,
        public dcpp::TimerManagerListener
{
public:
    static BridgeListeners& getInstance() {
        static BridgeListeners instance;
        return instance;
    }

    // ----- Setup / teardown -----

    void setBridge(DCBridge* bridge) {
        std::lock_guard<std::mutex> lk(m_mutex);
        m_bridge = bridge;
    }

    void setCallback(DCClientCallback* cb) {
        std::lock_guard<std::mutex> lk(m_mutex);
        m_callback = cb;
    }

    /// Subscribe to global managers (call once after dcpp::startup)
    void subscribeGlobal() {
        dcpp::SearchManager::getInstance()->addListener(this);
        dcpp::QueueManager::getInstance()->addListener(this);
        dcpp::DownloadManager::getInstance()->addListener(this);
        dcpp::UploadManager::getInstance()->addListener(this);
        dcpp::TimerManager::getInstance()->addListener(this);
    }

    /// Unsubscribe from global managers (call before dcpp::shutdown)
    void unsubscribeGlobal() {
        dcpp::TimerManager::getInstance()->removeListener(this);
        dcpp::UploadManager::getInstance()->removeListener(this);
        dcpp::DownloadManager::getInstance()->removeListener(this);
        dcpp::QueueManager::getInstance()->removeListener(this);
        dcpp::SearchManager::getInstance()->removeListener(this);
    }

    /// Attach to a specific hub client
    void attach(dcpp::Client* client, DCBridge* bridge) {
        std::lock_guard<std::mutex> lk(m_mutex);
        m_bridge = bridge;
        client->addListener(this);
    }

    /// Detach from a specific hub client
    void detach(dcpp::Client* client) {
        client->removeListener(this);
    }

    // =================================================================
    // ClientListener overrides
    // =================================================================

    void on(dcpp::ClientListener::Connecting, dcpp::Client* c) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onHubConnecting(c->getHubUrl());
    }

    void on(dcpp::ClientListener::Connected, dcpp::Client* c) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onHubConnected(c->getHubUrl(), c->getHubName());
    }

    void on(dcpp::ClientListener::Failed, dcpp::Client* c,
            const std::string& reason) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onHubDisconnected(c->getHubUrl(), reason);
    }

    void on(dcpp::ClientListener::Redirect, dcpp::Client* c,
            const std::string& newUrl) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onHubRedirect(c->getHubUrl(), newUrl);
    }

    void on(dcpp::ClientListener::GetPassword, dcpp::Client* c) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onHubPasswordRequest(c->getHubUrl());
    }

    void on(dcpp::ClientListener::HubUpdated, dcpp::Client* c) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onHubUpdated(c->getHubUrl(), c->getHubName());
    }

    void on(dcpp::ClientListener::NickTaken, dcpp::Client* c) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onNickTaken(c->getHubUrl());
    }

    void on(dcpp::ClientListener::HubFull, dcpp::Client* c) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onHubFull(c->getHubUrl());
    }

    void on(dcpp::ClientListener::Message, dcpp::Client* c,
            const dcpp::ChatMessage& msg) noexcept override {
        std::string hubUrl = c->getHubUrl();
        std::string nick;
        std::string text = msg.text;

        if (msg.from) {
            nick = msg.from->getIdentity().getNick();
        }

        // Stash in chat history via bridge
        stashChat(hubUrl, nick, text);

        auto cb = getCallback();
        if (!cb) return;

        // Determine if it was private or public
        if (msg.to && msg.to->getIdentity().getNick().size() > 0) {
            std::string toNick = msg.to->getIdentity().getNick();
            cb->onPrivateMessage(hubUrl, nick, toNick, text);
        } else {
            cb->onChatMessage(hubUrl, nick, text, msg.thirdPerson);
        }
    }

    void on(dcpp::ClientListener::StatusMessage, dcpp::Client* c,
            const std::string& msg, int flags) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onStatusMessage(c->getHubUrl(), msg);
    }

    void on(dcpp::ClientListener::UserUpdated, dcpp::Client* c,
            const dcpp::OnlineUser& ou) noexcept override {
        stashUserUpdate(c->getHubUrl(), ou);
        auto cb = getCallback();
        if (cb) cb->onUserConnected(c->getHubUrl(), ou.getIdentity().getNick());
    }

    void on(dcpp::ClientListener::UsersUpdated, dcpp::Client* c,
            const dcpp::OnlineUserList& list) noexcept override {
        auto cb = getCallback();
        for (auto& ou : list) {
            stashUserUpdate(c->getHubUrl(), *ou);
            if (cb) cb->onUserUpdated(c->getHubUrl(), ou->getIdentity().getNick());
        }
    }

    void on(dcpp::ClientListener::UserRemoved, dcpp::Client* c,
            const dcpp::OnlineUser& ou) noexcept override {
        stashUserRemove(c->getHubUrl(), ou.getIdentity().getNick());
        auto cb = getCallback();
        if (cb) cb->onUserDisconnected(c->getHubUrl(), ou.getIdentity().getNick());
    }

    void on(dcpp::ClientListener::SearchFlood, dcpp::Client* c,
            const std::string& msg) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onStatusMessage(c->getHubUrl(),
                                    "Search flood: " + msg);
    }

    void on(dcpp::ClientListener::NmdcSearch, dcpp::Client* c,
            const std::string& seeker, int searchType, int64_t size,
            int fileType, const std::string& searchStr) noexcept override {
        // No action needed — the search is handled internally by
        // ShareManager via the hub connection.
    }

    // =================================================================
    // SearchManagerListener overrides
    // =================================================================

    void on(dcpp::SearchManagerListener::SR,
            const dcpp::SearchResultPtr& sr) noexcept override {
        auto info = infoFromSearchResult(sr);

        // Store result in hub data
        stashSearchResult(info);

        auto cb = getCallback();
        if (cb) cb->onSearchResult(info.hubUrl, info.file, info.size,
                                    info.freeSlots, info.totalSlots,
                                    info.tth, info.nick, info.isDirectory);
    }

    // =================================================================
    // QueueManagerListener overrides
    // =================================================================

    void on(dcpp::QueueManagerListener::Added,
            dcpp::QueueItem* qi) noexcept override {
        auto cb = getCallback();
        if (cb) {
            cb->onQueueItemAdded(qi->getTarget(), qi->getSize(),
                                 qi->getTTH().toBase32());
        }
    }

    void on(dcpp::QueueManagerListener::Finished,
            dcpp::QueueItem* qi,
            const std::string& dir, int64_t speed) noexcept override {
        auto cb = getCallback();
        if (cb) {
            cb->onQueueItemFinished(qi->getTarget(), qi->getSize());
        }
    }

    void on(dcpp::QueueManagerListener::Removed,
            dcpp::QueueItem* qi) noexcept override {
        auto cb = getCallback();
        if (cb) {
            std::string target = qi->getTarget();
            cb->onQueueItemRemoved(target);
        }
    }

    void on(dcpp::QueueManagerListener::Moved,
            dcpp::QueueItem* qi,
            const std::string& oldTarget) noexcept override {
        // Item was moved to a new target path — report as new queue addition
        auto cb = getCallback();
        if (cb) {
            cb->onQueueItemAdded(qi->getTarget(), qi->getSize(),
                                 qi->getTTH().toBase32());
        }
    }

    // =================================================================
    // DownloadManagerListener overrides
    // =================================================================

    void on(dcpp::DownloadManagerListener::Starting,
            dcpp::Download* dl) noexcept override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromDownload(dl);
            cb->onDownloadStarting(ti.filename, ti.nick, ti.size);
        }
    }

    void on(dcpp::DownloadManagerListener::Complete,
            dcpp::Download* dl) noexcept override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromDownload(dl);
            cb->onDownloadComplete(ti.filename, ti.nick, ti.size, ti.speed);
        }
    }

    void on(dcpp::DownloadManagerListener::Failed,
            dcpp::Download* dl,
            const std::string& reason) noexcept override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromDownload(dl);
            cb->onDownloadFailed(ti.filename, reason);
        }
    }

    void on(dcpp::DownloadManagerListener::Tick,
            const dcpp::DownloadList& list) noexcept override {
        // Periodic download progress — could aggregate or skip for now
    }

    // =================================================================
    // UploadManagerListener overrides
    // =================================================================

    void on(dcpp::UploadManagerListener::Starting,
            dcpp::Upload* ul) noexcept override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromUpload(ul);
            cb->onUploadStarting(ti.filename, ti.nick, ti.size);
        }
    }

    void on(dcpp::UploadManagerListener::Complete,
            dcpp::Upload* ul) noexcept override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromUpload(ul);
            cb->onUploadComplete(ti.filename, ti.nick, ti.size);
        }
    }

    void on(dcpp::UploadManagerListener::Failed,
            dcpp::Upload* ul,
            const std::string& reason) noexcept override {
        // Upload failure — report as status
        auto cb = getCallback();
        if (cb) cb->onStatusMessage("", "Upload failed: " + reason);
    }

    void on(dcpp::UploadManagerListener::Tick,
            const dcpp::UploadList& list) noexcept override {
        // Periodic upload progress — could aggregate or skip for now
    }

    // =================================================================
    // TimerManagerListener overrides
    // =================================================================

    void on(dcpp::TimerManagerListener::Second,
            uint64_t tick) noexcept override {
        // Periodic tick — could be used for keepalive, stats, etc.
    }

private:
    BridgeListeners() = default;

    DCClientCallback* getCallback() {
        std::lock_guard<std::mutex> lk(m_mutex);
        return m_callback;
    }

    void stashChat(const std::string& hubUrl,
                   const std::string& nick,
                   const std::string& text);

    void stashSearchResult(const SearchResultInfo& info);

    void stashUserUpdate(const std::string& hubUrl,
                         const dcpp::OnlineUser& ou);

    void stashUserRemove(const std::string& hubUrl,
                         const std::string& nick);

    void clearHubUsers(const std::string& hubUrl);

    std::mutex m_mutex;
    DCBridge* m_bridge = nullptr;
    DCClientCallback* m_callback = nullptr;
};

} // namespace eiskaltdcpp_py
