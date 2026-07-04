/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * bridge_listeners.h — Implements dcpp listener interfaces and routes
 *                      events to our DCClientCallback.
 *
 * The dcpp core uses a Speaker/Listener observer pattern: managers inherit
 * Speaker<XyzListener> and fire events via tagged overloads of on().
 * This file provides BridgeListeners, owned by EisPyContext, that subscribes to all
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
#include <dcpp/DCPlusPlus.h>
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

#ifdef WITH_NMDCPB
#include <dcpp/NmdcHub.h>        // brings in ChannelManager.h + CallManager.h
#endif

#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <utility>

// Forward declare
namespace eiskaltdcpp_py {
class EisPyContext;
}

namespace eiskaltdcpp_py {

#ifdef WITH_NMDCPB
class BridgeListeners;  // forward for adapter owner pointers

// -------------------------------------------------------------------------
// Per-hub adapters bridging the ChannelManager/CallManager listener
// interfaces (which carry no hub URL) to BridgeListeners, capturing the
// owning hub URL so events can be routed to the Python callback.
// Method bodies are defined out-of-line below, after BridgeListeners.
// -------------------------------------------------------------------------
class ChannelCallbackAdapter : public dcpp::ChannelManagerListener {
public:
    ChannelCallbackAdapter(BridgeListeners* owner, std::string hubUrl)
        : owner_(owner), hubUrl_(std::move(hubUrl)) {}

    void onChannelList(const std::vector<dcpp::ChannelInfo>& channels) override;
    void onChannelCreated(const std::string& channelId,
                          const std::string& ownerNick, bool isPrivate) override;
    void onChannelMemberUpdate(const std::string& channelId, const std::string& nick,
                               int updateType, dcpp::ChannelRole newRole,
                               const std::string& reason) override;
    void onChannelMessage(const std::string& channelId, const std::string& fromNick,
                          const std::string& text, bool isAction,
                          uint64_t timestamp) override;
    void onChannelInvite(const std::string& channelId, const std::string& targetNick,
                         const std::string& inviterNick) override;
    void onChannelMessageUndecryptable(const std::string& channelId,
                                       const std::string& fromNick,
                                       uint32_t senderKeyId) override;
    void onSenderKeyRotation(const std::string& channelId, const std::string& reason,
                             const std::string& triggerNick) override;

private:
    BridgeListeners* owner_;
    std::string hubUrl_;
};

class CallCallbackAdapter : public dcpp::CallManagerListener {
public:
    CallCallbackAdapter(BridgeListeners* owner, std::string hubUrl)
        : owner_(owner), hubUrl_(std::move(hubUrl)) {}

    void onCallOffer(const std::string& callId, const std::string& fromNick,
                     bool isGroup,
                     const std::vector<dcpp::CallMediaType>& media) override;
    void onCallAnswer(const std::string& callId, const std::string& fromNick,
                      bool accepted, const std::string& rejectReason) override;
    void onCallCandidate(const std::string& callId, const std::string& fromNick,
                         const std::string& candidate) override;
    void onCallEnd(const std::string& callId, dcpp::CallEndReason reason,
                   uint32_t durationSec) override;
    void onCallMediaControl(const std::string& callId, const std::string& fromNick,
                            bool audioMuted, bool videoMuted,
                            bool screenSharing) override;

private:
    BridgeListeners* owner_;
    std::string hubUrl_;
};
#endif // WITH_NMDCPB

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
        auto nicks = dcpp::getContext()->getClientManager()->getNicks(
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
        auto nicks = dcpp::getContext()->getClientManager()->getNicks(dl->getHintedUser());
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
        auto nicks = dcpp::getContext()->getClientManager()->getNicks(ul->getHintedUser());
        ti.nick = nicks.empty() ? "" : nicks[0];
        ti.hubUrl = ul->getHintedUser().hint;
    }
    return ti;
}

// =========================================================================
// BridgeListeners — implements all dcpp listener protocols, owned by DCBridge
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
    explicit BridgeListeners(EisPyContext& bridge)
        : bridge_(bridge) {}

    // Non-copyable
    BridgeListeners(const BridgeListeners&) = delete;
    BridgeListeners& operator=(const BridgeListeners&) = delete;

    // ----- Setup / teardown -----

    void setCallback(DCClientCallback* cb) {
        std::lock_guard<std::mutex> lk(m_mutex);
        m_callback = cb;
    }

    /// Subscribe to global managers (call once after dcpp::startup)
    void subscribeGlobal() {
        dcpp::getContext()->getSearchManager()->addListener(this);
        dcpp::getContext()->getQueueManager()->addListener(this);
        dcpp::getContext()->getDownloadManager()->addListener(this);
        dcpp::getContext()->getUploadManager()->addListener(this);
        dcpp::getContext()->getTimerManager()->addListener(this);
    }

    /// Unsubscribe from global managers (call before dcpp::shutdown)
    void unsubscribeGlobal() {
        dcpp::getContext()->getTimerManager()->removeListener(this);
        dcpp::getContext()->getUploadManager()->removeListener(this);
        dcpp::getContext()->getDownloadManager()->removeListener(this);
        dcpp::getContext()->getQueueManager()->removeListener(this);
        dcpp::getContext()->getSearchManager()->removeListener(this);
    }

    /// Attach to a specific hub client
    void attach(dcpp::Client* client) {
        client->addListener(this);
#ifdef WITH_NMDCPB
        if (auto* hub = dynamic_cast<dcpp::NmdcHub*>(client)) {
            std::lock_guard<std::mutex> lk(m_mutex);
            const std::string url = hub->getHubUrl();
            auto chAdapter = std::make_unique<ChannelCallbackAdapter>(this, url);
            auto callAdapter = std::make_unique<CallCallbackAdapter>(this, url);
            hub->getChannelManager().addListener(chAdapter.get());
            hub->getCallManager().addListener(callAdapter.get());
            m_channelAdapters[client] = std::move(chAdapter);
            m_callAdapters[client] = std::move(callAdapter);
        }
#endif
    }

    /// Detach from a specific hub client
    void detach(dcpp::Client* client) {
        client->removeListener(this);
#ifdef WITH_NMDCPB
        if (auto* hub = dynamic_cast<dcpp::NmdcHub*>(client)) {
            std::lock_guard<std::mutex> lk(m_mutex);
            auto chIt = m_channelAdapters.find(client);
            if (chIt != m_channelAdapters.end()) {
                hub->getChannelManager().removeListener(chIt->second.get());
                m_channelAdapters.erase(chIt);
            }
            auto callIt = m_callAdapters.find(client);
            if (callIt != m_callAdapters.end()) {
                hub->getCallManager().removeListener(callIt->second.get());
                m_callAdapters.erase(callIt);
            }
        }
#endif
    }

    // =================================================================
    // ClientListener overrides
    // =================================================================

    void on(dcpp::ClientListener::Connecting, dcpp::Client* c) override {
        auto cb = getCallback();
        if (cb) cb->onHubConnecting(c->getHubUrl());
    }

    void on(dcpp::ClientListener::Connected, dcpp::Client* c) override {
        refreshHubCache(c->getHubUrl(), c);
        auto cb = getCallback();
        if (cb) cb->onHubConnected(c->getHubUrl(), c->getHubName());
    }

    void on(dcpp::ClientListener::Failed, dcpp::Client* c,
            const std::string& reason) override {
        markHubDisconnected(c->getHubUrl());
        auto cb = getCallback();
        if (cb) cb->onHubDisconnected(c->getHubUrl(), reason);
    }

    void on(dcpp::ClientListener::Redirect, dcpp::Client* c,
            const std::string& newUrl) override {
        auto cb = getCallback();
        if (cb) cb->onHubRedirect(c->getHubUrl(), newUrl);
    }

    void on(dcpp::ClientListener::GetPassword, dcpp::Client* c) override {
        auto cb = getCallback();
        if (cb) cb->onHubPasswordRequest(c->getHubUrl());
    }

    void on(dcpp::ClientListener::HubUpdated, dcpp::Client* c) override {
        refreshHubCache(c->getHubUrl(), c);
        auto cb = getCallback();
        if (cb) cb->onHubUpdated(c->getHubUrl(), c->getHubName());
    }

    void on(dcpp::ClientListener::NickTaken, dcpp::Client* c) override {
        auto cb = getCallback();
        if (cb) cb->onNickTaken(c->getHubUrl());
    }

    void on(dcpp::ClientListener::HubFull, dcpp::Client* c) override {
        auto cb = getCallback();
        if (cb) cb->onHubFull(c->getHubUrl());
    }

    void on(dcpp::ClientListener::Message, dcpp::Client* c,
            const dcpp::ChatMessage& msg) override {
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
            const std::string& msg, int flags) override {
        auto cb = getCallback();
        if (cb) cb->onStatusMessage(c->getHubUrl(), msg);
    }

    void on(dcpp::ClientListener::UserUpdated, dcpp::Client* c,
            const dcpp::OnlineUser& ou) override {
        stashUserUpdate(c->getHubUrl(), ou);
        refreshHubCache(c->getHubUrl(), c);
        auto cb = getCallback();
        if (cb) cb->onUserConnected(c->getHubUrl(), ou.getIdentity().getNick());
    }

    void on(dcpp::ClientListener::UsersUpdated, dcpp::Client* c,
            const dcpp::OnlineUserList& list) override {
        auto cb = getCallback();
        for (auto& ou : list) {
            stashUserUpdate(c->getHubUrl(), *ou);
            if (cb) cb->onUserUpdated(c->getHubUrl(), ou->getIdentity().getNick());
        }
        // Refresh once after batch — user count / share total may have changed
        refreshHubCache(c->getHubUrl(), c);
    }

    void on(dcpp::ClientListener::UserRemoved, dcpp::Client* c,
            const dcpp::OnlineUser& ou) override {
        stashUserRemove(c->getHubUrl(), ou.getIdentity().getNick());
        refreshHubCache(c->getHubUrl(), c);
        auto cb = getCallback();
        if (cb) cb->onUserDisconnected(c->getHubUrl(), ou.getIdentity().getNick());
    }

    void on(dcpp::ClientListener::SearchFlood, dcpp::Client* c,
            const std::string& msg) override {
        auto cb = getCallback();
        if (cb) cb->onStatusMessage(c->getHubUrl(),
                                    "Search flood: " + msg);
    }

    void on(dcpp::ClientListener::NmdcPbMessage, dcpp::Client* c,
            const std::string& cmd, const std::string& nick,
            const std::string& data) noexcept override {
        auto cb = getCallback();
        if (cb) cb->onNmdcPbMessage(c->getHubUrl(), cmd, nick, data);
    }

#ifdef WITH_NMDCPB
    // =================================================================
    // NMDCpb Channel/Call forwarding (called by the per-hub adapters)
    // =================================================================

    void fwdChannelListUpdated(const std::string& hubUrl) {
        auto cb = getCallback();
        if (cb) cb->onChannelListUpdated(hubUrl);
    }
    void fwdChannelCreated(const std::string& hubUrl, const std::string& channelId,
                           const std::string& ownerNick, bool isPrivate) {
        auto cb = getCallback();
        if (cb) cb->onChannelCreated(hubUrl, channelId, ownerNick, isPrivate);
    }
    void fwdChannelMemberUpdate(const std::string& hubUrl, const std::string& channelId,
                                const std::string& nick, int updateType, int role,
                                const std::string& reason) {
        auto cb = getCallback();
        if (cb) cb->onChannelMemberUpdate(hubUrl, channelId, nick, updateType, role,
                                          reason);
    }
    void fwdChannelMessage(const std::string& hubUrl, const std::string& channelId,
                           const std::string& fromNick, const std::string& text,
                           bool isAction, uint64_t timestamp) {
        auto cb = getCallback();
        if (cb) cb->onChannelMessage(hubUrl, channelId, fromNick, text, isAction,
                                     timestamp);
    }
    void fwdChannelInvite(const std::string& hubUrl, const std::string& channelId,
                          const std::string& targetNick,
                          const std::string& inviterNick) {
        auto cb = getCallback();
        if (cb) cb->onChannelInvite(hubUrl, channelId, targetNick, inviterNick);
    }
    void fwdChannelMessageUndecryptable(const std::string& hubUrl,
                                        const std::string& channelId,
                                        const std::string& fromNick, uint32_t keyId) {
        auto cb = getCallback();
        if (cb) cb->onChannelMessageUndecryptable(hubUrl, channelId, fromNick, keyId);
    }
    void fwdSenderKeyRotation(const std::string& hubUrl, const std::string& channelId,
                              const std::string& reason,
                              const std::string& triggerNick) {
        auto cb = getCallback();
        if (cb) cb->onSenderKeyRotation(hubUrl, channelId, reason, triggerNick);
    }
    void fwdCallOffer(const std::string& hubUrl, const std::string& callId,
                      const std::string& fromNick, bool isGroup,
                      const std::string& mediaCsv) {
        auto cb = getCallback();
        if (cb) cb->onCallOffer(hubUrl, callId, fromNick, isGroup, mediaCsv);
    }
    void fwdCallAnswer(const std::string& hubUrl, const std::string& callId,
                       const std::string& fromNick, bool accepted,
                       const std::string& rejectReason) {
        auto cb = getCallback();
        if (cb) cb->onCallAnswer(hubUrl, callId, fromNick, accepted, rejectReason);
    }
    void fwdCallCandidate(const std::string& hubUrl, const std::string& callId,
                          const std::string& fromNick, const std::string& candidate) {
        auto cb = getCallback();
        if (cb) cb->onCallCandidate(hubUrl, callId, fromNick, candidate);
    }
    void fwdCallEnd(const std::string& hubUrl, const std::string& callId, int reason,
                    uint32_t durationSec) {
        auto cb = getCallback();
        if (cb) cb->onCallEnd(hubUrl, callId, reason, durationSec);
    }
    void fwdCallMediaControl(const std::string& hubUrl, const std::string& callId,
                             const std::string& fromNick, bool audioMuted,
                             bool videoMuted, bool screenSharing) {
        auto cb = getCallback();
        if (cb) cb->onCallMediaControl(hubUrl, callId, fromNick, audioMuted, videoMuted,
                                       screenSharing);
    }
#endif // WITH_NMDCPB

    // =================================================================
    // SearchManagerListener overrides
    // =================================================================

    void on(dcpp::SearchManagerListener::SR,
            const dcpp::SearchResultPtr& sr) override {
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
            dcpp::QueueItem* qi) override {
        auto cb = getCallback();
        if (cb) {
            cb->onQueueItemAdded(qi->getTarget(), qi->getSize(),
                                 qi->getTTH().toBase32());
        }
    }

    void on(dcpp::QueueManagerListener::Finished,
            dcpp::QueueItem* qi,
            const std::string& dir, int64_t speed) override {
        auto cb = getCallback();
        if (cb) {
            cb->onQueueItemFinished(qi->getTarget(), qi->getSize());
        }
    }

    void on(dcpp::QueueManagerListener::Removed,
            dcpp::QueueItem* qi) override {
        auto cb = getCallback();
        if (cb) {
            std::string target = qi->getTarget();
            cb->onQueueItemRemoved(target);
        }
    }

    void on(dcpp::QueueManagerListener::Moved,
            dcpp::QueueItem* qi,
            const std::string& oldTarget) override {
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
            dcpp::Download* dl) override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromDownload(dl);
            cb->onDownloadStarting(ti.filename, ti.nick, ti.size);
        }
    }

    void on(dcpp::DownloadManagerListener::Complete,
            dcpp::Download* dl) override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromDownload(dl);
            cb->onDownloadComplete(ti.filename, ti.nick, ti.size, ti.speed);
        }
    }

    void on(dcpp::DownloadManagerListener::Failed,
            dcpp::Download* dl,
            const std::string& reason) override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromDownload(dl);
            cb->onDownloadFailed(ti.filename, reason);
        }
    }

    void on(dcpp::DownloadManagerListener::Tick,
            const dcpp::DownloadList& list) override {
        // Periodic download progress — could aggregate or skip for now
    }

    // =================================================================
    // UploadManagerListener overrides
    // =================================================================

    void on(dcpp::UploadManagerListener::Starting,
            dcpp::Upload* ul) override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromUpload(ul);
            cb->onUploadStarting(ti.filename, ti.nick, ti.size);
        }
    }

    void on(dcpp::UploadManagerListener::Complete,
            dcpp::Upload* ul) override {
        auto cb = getCallback();
        if (cb) {
            auto ti = infoFromUpload(ul);
            cb->onUploadComplete(ti.filename, ti.nick, ti.size);
        }
    }

    void on(dcpp::UploadManagerListener::Failed,
            dcpp::Upload* ul,
            const std::string& reason) override {
        // Upload failure — report as status
        auto cb = getCallback();
        if (cb) cb->onStatusMessage("", "Upload failed: " + reason);
    }

    void on(dcpp::UploadManagerListener::Tick,
            const dcpp::UploadList& list) override {
        // Periodic upload progress — could aggregate or skip for now
    }

    // =================================================================
    // TimerManagerListener overrides
    // =================================================================

    void on(dcpp::TimerManagerListener::Second,
            uint64_t tick) override {
        // Periodic tick — could be used for keepalive, stats, etc.
    }

private:
    BridgeListeners() = delete;

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

    /// Snapshot Client* accessors into HubData::cachedInfo under m_mutex.
    /// MUST be called from the socket thread (callback context) where
    /// Client* access is safe.  NmdcHub::cs is recursive, so calling
    /// getUserCount() while already under cs (some callbacks fire under
    /// cs) is fine.
    void refreshHubCache(const std::string& hubUrl, dcpp::Client* c);

    /// Lightweight cache update for disconnect — sets connected=false
    /// without reading Client* accessors that may already be invalid.
    void markHubDisconnected(const std::string& hubUrl);

    std::mutex m_mutex;
    EisPyContext& bridge_;
    DCClientCallback* m_callback = nullptr;
#ifdef WITH_NMDCPB
    // Per-hub manager listener adapters (keyed by Client*), guarded by m_mutex.
    std::map<dcpp::Client*, std::unique_ptr<ChannelCallbackAdapter>> m_channelAdapters;
    std::map<dcpp::Client*, std::unique_ptr<CallCallbackAdapter>> m_callAdapters;
#endif
};

#ifdef WITH_NMDCPB
// -------------------------------------------------------------------------
// Adapter method bodies (defined here, after BridgeListeners is complete).
// -------------------------------------------------------------------------
inline void ChannelCallbackAdapter::onChannelList(
        const std::vector<dcpp::ChannelInfo>& /*channels*/) {
    owner_->fwdChannelListUpdated(hubUrl_);
}
inline void ChannelCallbackAdapter::onChannelCreated(
        const std::string& channelId, const std::string& ownerNick, bool isPrivate) {
    owner_->fwdChannelCreated(hubUrl_, channelId, ownerNick, isPrivate);
}
inline void ChannelCallbackAdapter::onChannelMemberUpdate(
        const std::string& channelId, const std::string& nick, int updateType,
        dcpp::ChannelRole newRole, const std::string& reason) {
    owner_->fwdChannelMemberUpdate(hubUrl_, channelId, nick, updateType,
                                   static_cast<int>(newRole), reason);
}
inline void ChannelCallbackAdapter::onChannelMessage(
        const std::string& channelId, const std::string& fromNick,
        const std::string& text, bool isAction, uint64_t timestamp) {
    owner_->fwdChannelMessage(hubUrl_, channelId, fromNick, text, isAction, timestamp);
}
inline void ChannelCallbackAdapter::onChannelInvite(
        const std::string& channelId, const std::string& targetNick,
        const std::string& inviterNick) {
    owner_->fwdChannelInvite(hubUrl_, channelId, targetNick, inviterNick);
}
inline void ChannelCallbackAdapter::onChannelMessageUndecryptable(
        const std::string& channelId, const std::string& fromNick,
        uint32_t senderKeyId) {
    owner_->fwdChannelMessageUndecryptable(hubUrl_, channelId, fromNick, senderKeyId);
}
inline void ChannelCallbackAdapter::onSenderKeyRotation(
        const std::string& channelId, const std::string& reason,
        const std::string& triggerNick) {
    owner_->fwdSenderKeyRotation(hubUrl_, channelId, reason, triggerNick);
}

inline void CallCallbackAdapter::onCallOffer(
        const std::string& callId, const std::string& fromNick, bool isGroup,
        const std::vector<dcpp::CallMediaType>& media) {
    std::string csv;
    for (size_t i = 0; i < media.size(); ++i) {
        if (i) csv += ',';
        csv += std::to_string(static_cast<int>(media[i]));
    }
    owner_->fwdCallOffer(hubUrl_, callId, fromNick, isGroup, csv);
}
inline void CallCallbackAdapter::onCallAnswer(
        const std::string& callId, const std::string& fromNick, bool accepted,
        const std::string& rejectReason) {
    owner_->fwdCallAnswer(hubUrl_, callId, fromNick, accepted, rejectReason);
}
inline void CallCallbackAdapter::onCallCandidate(
        const std::string& callId, const std::string& fromNick,
        const std::string& candidate) {
    owner_->fwdCallCandidate(hubUrl_, callId, fromNick, candidate);
}
inline void CallCallbackAdapter::onCallEnd(
        const std::string& callId, dcpp::CallEndReason reason, uint32_t durationSec) {
    owner_->fwdCallEnd(hubUrl_, callId, static_cast<int>(reason), durationSec);
}
inline void CallCallbackAdapter::onCallMediaControl(
        const std::string& callId, const std::string& fromNick, bool audioMuted,
        bool videoMuted, bool screenSharing) {
    owner_->fwdCallMediaControl(hubUrl_, callId, fromNick, audioMuted, videoMuted,
                                screenSharing);
}
#endif // WITH_NMDCPB

} // namespace eiskaltdcpp_py
