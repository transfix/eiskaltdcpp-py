/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * Copyright (C) 2026 Verlihub Team
 * Licensed under GPL-3.0-or-later
 *
 * listener_adapters.h — Python-friendly adapter classes for dcpp listeners.
 *
 * The dcpp core uses tagged dispatch: `on(TagType, args...)`.
 * SWIG can't directly wrap these because all overloads share the name "on".
 * These adapters inherit from the dcpp listener, override the on() tags,
 * and dispatch to distinctly-named virtual methods that SWIG directors
 * can expose to Python.
 *
 * Python subclasses override the named methods (onConnecting, onFailed, etc.).
 * SWIG directors automatically acquire the GIL when calling into Python.
 *
 * The adapters pass Python-safe types (strings, ints, our types.h structs)
 * rather than raw dcpp pointers, which have complex C++ lifetimes.
 */

#pragma once

#include "types.h"
#include "bridge_listeners.h"  // for helper converters (userFromOnlineUser, etc.)

#include <dcpp/Client.h>
#include <dcpp/ClientListener.h>
#include <dcpp/ClientManager.h>
#include <dcpp/ClientManagerListener.h>
#include <dcpp/ChatMessage.h>
#include <dcpp/CID.h>
#include <dcpp/Download.h>
#include <dcpp/DownloadManager.h>
#include <dcpp/DownloadManagerListener.h>
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

#include <string>
#include <cstdint>

namespace eiskaltdcpp_py {

// =========================================================================
// PyClientListener — per-hub events (connect, chat, users)
// =========================================================================

class PyClientListener : public dcpp::ClientListener {
public:
    virtual ~PyClientListener() {}

    // Named virtual methods — override these in Python
    virtual void onConnecting(const std::string& hubUrl) {}
    virtual void onConnected(const std::string& hubUrl) {}
    virtual void onFailed(const std::string& hubUrl, const std::string& reason) {}
    virtual void onRedirect(const std::string& hubUrl, const std::string& newUrl) {}
    virtual void onGetPassword(const std::string& hubUrl) {}
    virtual void onHubUpdated(const std::string& hubUrl) {}
    virtual void onNickTaken(const std::string& hubUrl) {}
    virtual void onHubFull(const std::string& hubUrl) {}
    virtual void onSearchFlood(const std::string& hubUrl, const std::string& msg) {}
    virtual void onMessage(const std::string& hubUrl, const std::string& nick,
                           const std::string& text, bool thirdPerson) {}
    virtual void onStatusMessage(const std::string& hubUrl, const std::string& msg,
                                 int flags) {}
    virtual void onUserUpdated(const std::string& hubUrl, const UserInfo& user) {}
    virtual void onUsersUpdated(const std::string& hubUrl) {}
    virtual void onUserRemoved(const std::string& hubUrl, const UserInfo& user) {}
    virtual void onHubUserCommand(const std::string& hubUrl, int type, int ctx,
                                  const std::string& name,
                                  const std::string& command) {}

protected:
    // dcpp::ClientListener overrides — dispatch to named methods
    void on(Connecting, dcpp::Client* c) noexcept override {
        onConnecting(c->getHubUrl());
    }
    void on(Connected, dcpp::Client* c) noexcept override {
        onConnected(c->getHubUrl());
    }
    void on(Failed, dcpp::Client* c, const std::string& reason) noexcept override {
        onFailed(c->getHubUrl(), reason);
    }
    void on(Redirect, dcpp::Client* c, const std::string& newUrl) noexcept override {
        onRedirect(c->getHubUrl(), newUrl);
    }
    void on(GetPassword, dcpp::Client* c) noexcept override {
        onGetPassword(c->getHubUrl());
    }
    void on(HubUpdated, dcpp::Client* c) noexcept override {
        onHubUpdated(c->getHubUrl());
    }
    void on(NickTaken, dcpp::Client* c) noexcept override {
        onNickTaken(c->getHubUrl());
    }
    void on(HubFull, dcpp::Client* c) noexcept override {
        onHubFull(c->getHubUrl());
    }
    void on(SearchFlood, dcpp::Client* c, const std::string& msg) noexcept override {
        onSearchFlood(c->getHubUrl(), msg);
    }
    void on(Message, dcpp::Client* c, const dcpp::ChatMessage& cm) noexcept override {
        std::string nick;
        bool thirdPerson = cm.thirdPerson;
        if (cm.from) {
            nick = cm.from->getIdentity().getNick();
        }
        onMessage(c->getHubUrl(), nick, cm.text, thirdPerson);
    }
    void on(StatusMessage, dcpp::Client* c, const std::string& msg,
            int flags) noexcept override {
        onStatusMessage(c->getHubUrl(), msg, flags);
    }
    void on(UserUpdated, dcpp::Client* c, const dcpp::OnlineUser& ou) noexcept override {
        onUserUpdated(c->getHubUrl(), userFromOnlineUser(ou));
    }
    void on(UsersUpdated, dcpp::Client* c, const dcpp::OnlineUserList&) noexcept override {
        onUsersUpdated(c->getHubUrl());
    }
    void on(UserRemoved, dcpp::Client* c, const dcpp::OnlineUser& ou) noexcept override {
        onUserRemoved(c->getHubUrl(), userFromOnlineUser(ou));
    }
    void on(HubUserCommand, dcpp::Client* c, int type, int ctx,
            const std::string& name, const std::string& command) noexcept override {
        onHubUserCommand(c->getHubUrl(), type, ctx, name, command);
    }
    // NmdcSearch and AdcSearch are deliberately not exposed — too low-level
    // for Python users. Use search() + onSearchResult callback instead.
};

// =========================================================================
// PyClientManagerListener — global user/hub lifecycle events
// =========================================================================

class PyClientManagerListener : public dcpp::ClientManagerListener {
public:
    virtual ~PyClientManagerListener() {}

    virtual void onUserConnected(const std::string& cid) {}
    virtual void onUserUpdated(const std::string& hubUrl, const UserInfo& user) {}
    virtual void onUserDisconnected(const std::string& cid) {}
    virtual void onIncomingSearch(const std::string& searchString) {}
    virtual void onClientConnected(const std::string& hubUrl) {}
    virtual void onClientUpdated(const std::string& hubUrl) {}
    virtual void onClientDisconnected(const std::string& hubUrl) {}

protected:
    void on(dcpp::ClientManagerListener::UserConnected,
            const dcpp::UserPtr& user) noexcept override {
        onUserConnected(user->getCID().toBase32());
    }
    void on(dcpp::ClientManagerListener::UserUpdated,
            const dcpp::OnlineUser& ou) noexcept override {
        std::string hubUrl = ou.getClient().getHubUrl();
        onUserUpdated(hubUrl, userFromOnlineUser(ou));
    }
    void on(dcpp::ClientManagerListener::UserDisconnected,
            const dcpp::UserPtr& user) noexcept override {
        onUserDisconnected(user->getCID().toBase32());
    }
    void on(dcpp::ClientManagerListener::IncomingSearch,
            const std::string& s) noexcept override {
        onIncomingSearch(s);
    }
    void on(dcpp::ClientManagerListener::ClientConnected,
            dcpp::Client* c) noexcept override {
        onClientConnected(c->getHubUrl());
    }
    void on(dcpp::ClientManagerListener::ClientUpdated,
            dcpp::Client* c) noexcept override {
        onClientUpdated(c->getHubUrl());
    }
    void on(dcpp::ClientManagerListener::ClientDisconnected,
            dcpp::Client* c) noexcept override {
        onClientDisconnected(c->getHubUrl());
    }
};

// =========================================================================
// PySearchManagerListener — search result events
// =========================================================================

class PySearchManagerListener : public dcpp::SearchManagerListener {
public:
    virtual ~PySearchManagerListener() {}

    virtual void onSearchResult(const SearchResultInfo& result) {}

protected:
    // SearchManagerListener::on(SR, ...) is pure virtual in dcpp
    void on(dcpp::SearchManagerListener::SR,
            const dcpp::SearchResultPtr& sr) noexcept override {
        onSearchResult(infoFromSearchResult(sr));
    }
};

// =========================================================================
// PyQueueManagerListener — download queue events
// =========================================================================

class PyQueueManagerListener : public dcpp::QueueManagerListener {
public:
    virtual ~PyQueueManagerListener() {}

    // Core queue events
    virtual void onAdded(const std::string& target, int64_t size,
                         const std::string& tth) {}
    virtual void onFinished(const std::string& target, int64_t size,
                            const std::string& dir) {}
    virtual void onRemoved(const std::string& target) {}
    virtual void onMoved(const std::string& target, const std::string& newTarget) {}
    virtual void onSourcesUpdated(const std::string& target) {}
    virtual void onStatusUpdated(const std::string& target) {}
    virtual void onSearchStringUpdated(const std::string& target) {}
    virtual void onFileMoved(const std::string& target) {}

    // Recheck events
    virtual void onRecheckStarted(const std::string& target) {}
    virtual void onRecheckNoFile(const std::string& target) {}
    virtual void onRecheckFileTooSmall(const std::string& target) {}
    virtual void onRecheckDownloadsRunning(const std::string& target) {}
    virtual void onRecheckNoTree(const std::string& target) {}
    virtual void onRecheckAlreadyFinished(const std::string& target) {}
    virtual void onRecheckDone(const std::string& target) {}

    // Integrity events
    virtual void onCRCFailed(const std::string& target, const std::string& reason) {}
    virtual void onCRCChecked(const std::string& target) {}

    // Partial list
    virtual void onPartialList(const std::string& nick, const std::string& text) {}

protected:
    void on(Added, dcpp::QueueItem* qi) noexcept override {
        onAdded(qi->getTarget(), qi->getSize(), qi->getTTH().toBase32());
    }
    void on(Finished, dcpp::QueueItem* qi, const std::string& dir,
            int64_t) noexcept override {
        onFinished(qi->getTarget(), qi->getSize(), dir);
    }
    void on(Removed, dcpp::QueueItem* qi) noexcept override {
        onRemoved(qi->getTarget());
    }
    void on(Moved, dcpp::QueueItem* qi,
            const std::string& newTarget) noexcept override {
        onMoved(qi->getTarget(), newTarget);
    }
    void on(SourcesUpdated, dcpp::QueueItem* qi) noexcept override {
        onSourcesUpdated(qi->getTarget());
    }
    void on(StatusUpdated, dcpp::QueueItem* qi) noexcept override {
        onStatusUpdated(qi->getTarget());
    }
    void on(SearchStringUpdated, dcpp::QueueItem* qi) noexcept override {
        onSearchStringUpdated(qi->getTarget());
    }
    void on(FileMoved, const std::string& target) noexcept override {
        onFileMoved(target);
    }
    void on(RecheckStarted, const std::string& t) noexcept override {
        onRecheckStarted(t);
    }
    void on(RecheckNoFile, const std::string& t) noexcept override {
        onRecheckNoFile(t);
    }
    void on(RecheckFileTooSmall, const std::string& t) noexcept override {
        onRecheckFileTooSmall(t);
    }
    void on(RecheckDownloadsRunning, const std::string& t) noexcept override {
        onRecheckDownloadsRunning(t);
    }
    void on(RecheckNoTree, const std::string& t) noexcept override {
        onRecheckNoTree(t);
    }
    void on(RecheckAlreadyFinished, const std::string& t) noexcept override {
        onRecheckAlreadyFinished(t);
    }
    void on(RecheckDone, const std::string& t) noexcept override {
        onRecheckDone(t);
    }
    void on(CRCFailed, dcpp::Download* dl,
            const std::string& reason) noexcept override {
        std::string target = dl ? dl->getPath() : "";
        onCRCFailed(target, reason);
    }
    void on(CRCChecked, dcpp::Download* dl) noexcept override {
        std::string target = dl ? dl->getPath() : "";
        onCRCChecked(target);
    }
    void on(PartialList, const dcpp::HintedUser& hu,
            const std::string& text) noexcept override {
        std::string nick;
        if (hu.user) {
            auto nicks = dcpp::getContext()->getClientManager()->getNicks(hu);
            nick = nicks.empty() ? "" : nicks[0];
        }
        onPartialList(nick, text);
    }
};

// =========================================================================
// PyDownloadManagerListener — download progress events
// =========================================================================

class PyDownloadManagerListener : public dcpp::DownloadManagerListener {
public:
    virtual ~PyDownloadManagerListener() {}

    virtual void onRequesting(const TransferInfo& transfer) {}
    virtual void onStarting(const TransferInfo& transfer) {}
    virtual void onTick(const std::vector<TransferInfo>& transfers) {}
    virtual void onComplete(const TransferInfo& transfer) {}
    virtual void onFailed(const TransferInfo& transfer,
                          const std::string& reason) {}

protected:
    void on(Requesting, dcpp::Download* dl) noexcept override {
        onRequesting(infoFromDownload(dl));
    }
    void on(Starting, dcpp::Download* dl) noexcept override {
        onStarting(infoFromDownload(dl));
    }
    void on(dcpp::DownloadManagerListener::Tick,
            const dcpp::DownloadList& dls) noexcept override {
        std::vector<TransferInfo> transfers;
        transfers.reserve(dls.size());
        for (auto* dl : dls) {
            transfers.push_back(infoFromDownload(dl));
        }
        onTick(transfers);
    }
    void on(Complete, dcpp::Download* dl) noexcept override {
        onComplete(infoFromDownload(dl));
    }
    void on(dcpp::DownloadManagerListener::Failed, dcpp::Download* dl,
            const std::string& reason) noexcept override {
        onFailed(infoFromDownload(dl), reason);
    }
};

// =========================================================================
// PyUploadManagerListener — upload progress events
// =========================================================================

class PyUploadManagerListener : public dcpp::UploadManagerListener {
public:
    virtual ~PyUploadManagerListener() {}

    virtual void onStarting(const TransferInfo& transfer) {}
    virtual void onTick(const std::vector<TransferInfo>& transfers) {}
    virtual void onComplete(const TransferInfo& transfer) {}
    virtual void onFailed(const TransferInfo& transfer,
                          const std::string& reason) {}
    virtual void onWaitingAddFile(const std::string& nick,
                                  const std::string& filename) {}
    virtual void onWaitingRemoveUser(const std::string& nick) {}

protected:
    void on(Starting, dcpp::Upload* ul) noexcept override {
        onStarting(infoFromUpload(ul));
    }
    void on(dcpp::UploadManagerListener::Tick,
            const dcpp::UploadList& uls) noexcept override {
        std::vector<TransferInfo> transfers;
        transfers.reserve(uls.size());
        for (auto* ul : uls) {
            transfers.push_back(infoFromUpload(ul));
        }
        onTick(transfers);
    }
    void on(Complete, dcpp::Upload* ul) noexcept override {
        onComplete(infoFromUpload(ul));
    }
    void on(dcpp::UploadManagerListener::Failed, dcpp::Upload* ul,
            const std::string& reason) noexcept override {
        onFailed(infoFromUpload(ul), reason);
    }
    void on(WaitingAddFile, const dcpp::HintedUser& hu,
            const std::string& filename) noexcept override {
        std::string nick;
        if (hu.user) {
            auto nicks = dcpp::getContext()->getClientManager()->getNicks(hu);
            nick = nicks.empty() ? "" : nicks[0];
        }
        onWaitingAddFile(nick, filename);
    }
    void on(WaitingRemoveUser, const dcpp::HintedUser& hu) noexcept override {
        std::string nick;
        if (hu.user) {
            auto nicks = dcpp::getContext()->getClientManager()->getNicks(hu);
            nick = nicks.empty() ? "" : nicks[0];
        }
        onWaitingRemoveUser(nick);
    }
};

// =========================================================================
// PyTimerManagerListener — periodic timer events
// =========================================================================

class PyTimerManagerListener : public dcpp::TimerManagerListener {
public:
    virtual ~PyTimerManagerListener() {}

    virtual void onSecond(uint64_t tick) {}
    virtual void onMinute(uint64_t tick) {}

protected:
    void on(Second, uint64_t tick) noexcept override {
        onSecond(tick);
    }
    void on(Minute, uint64_t tick) noexcept override {
        onMinute(tick);
    }
};

} // namespace eiskaltdcpp_py
