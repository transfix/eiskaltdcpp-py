/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * Copyright (C) 2026 Verlihub Team
 * Licensed under GPL-3.0-or-later
 *
 * callbacks.h — Abstract callback interface for DC client events.
 *
 * This class is exposed to Python via SWIG directors, allowing Python
 * subclasses to override virtual methods and receive C++ events.
 */

#pragma once

#include <string>
#include <cstdint>

namespace eiskaltdcpp_py {

/**
 * Abstract callback interface for DC client events.
 *
 * Python users subclass this and override the methods they care about.
 * SWIG directors handle the C++ → Python dispatch and GIL acquisition.
 *
 * Example (Python):
 *     class MyHandler(eiskaltdcpp.DCClientCallback):
 *         def onChatMessage(self, hubUrl, nick, message, thirdPerson):
 *             print(f"<{nick}> {message}")
 *
 *         def onSearchResult(self, hubUrl, file, size, freeSlots,
 *                            totalSlots, tth, nick):
 *             print(f"Found: {file} ({size} bytes)")
 */
class DCClientCallback {
public:
    virtual ~DCClientCallback() {}

    // =====================================================================
    // Hub events
    // =====================================================================

    /// Hub is connecting.
    virtual void onHubConnecting(const std::string& hubUrl) {}

    /// Hub connection established.
    virtual void onHubConnected(const std::string& hubUrl,
                                const std::string& hubName) {}

    /// Hub disconnected.
    virtual void onHubDisconnected(const std::string& hubUrl,
                                   const std::string& reason) {}

    /// Hub sent a redirect.
    virtual void onHubRedirect(const std::string& hubUrl,
                               const std::string& newUrl) {}

    /// Hub requests a password.
    virtual void onHubPasswordRequest(const std::string& hubUrl) {}

    /// Hub name/topic updated.
    virtual void onHubUpdated(const std::string& hubUrl,
                              const std::string& hubName) {}

    /// Nick is already taken.
    virtual void onNickTaken(const std::string& hubUrl) {}

    /// Hub is full.
    virtual void onHubFull(const std::string& hubUrl) {}

    // =====================================================================
    // Chat events
    // =====================================================================

    /// Public chat message received.
    virtual void onChatMessage(const std::string& hubUrl,
                               const std::string& nick,
                               const std::string& message,
                               bool thirdPerson) {}

    /// Private message received.
    virtual void onPrivateMessage(const std::string& hubUrl,
                                  const std::string& fromNick,
                                  const std::string& toNick,
                                  const std::string& message) {}

    /// Hub status/info message.
    virtual void onStatusMessage(const std::string& hubUrl,
                                 const std::string& message) {}

    // =====================================================================
    // User events
    // =====================================================================

    /// User appeared on a hub.
    virtual void onUserConnected(const std::string& hubUrl,
                                 const std::string& nick) {}

    /// User left a hub.
    virtual void onUserDisconnected(const std::string& hubUrl,
                                    const std::string& nick) {}

    /// User info updated.
    virtual void onUserUpdated(const std::string& hubUrl,
                               const std::string& nick) {}

    // =====================================================================
    // Search events
    // =====================================================================

    /// Search result received.
    virtual void onSearchResult(const std::string& hubUrl,
                                const std::string& file,
                                int64_t size,
                                int freeSlots,
                                int totalSlots,
                                const std::string& tth,
                                const std::string& nick,
                                bool isDirectory) {}

    // =====================================================================
    // Transfer events
    // =====================================================================

    /// Download is starting.
    virtual void onDownloadStarting(const std::string& target,
                                    const std::string& nick,
                                    int64_t size) {}

    /// Download completed successfully.
    virtual void onDownloadComplete(const std::string& target,
                                    const std::string& nick,
                                    int64_t size,
                                    int64_t speed) {}

    /// Download failed.
    virtual void onDownloadFailed(const std::string& target,
                                  const std::string& reason) {}

    /// Upload is starting.
    virtual void onUploadStarting(const std::string& file,
                                  const std::string& nick,
                                  int64_t size) {}

    /// Upload completed.
    virtual void onUploadComplete(const std::string& file,
                                  const std::string& nick,
                                  int64_t size) {}

    // =====================================================================
    // Queue events
    // =====================================================================

    /// Item added to download queue.
    virtual void onQueueItemAdded(const std::string& target,
                                  int64_t size,
                                  const std::string& tth) {}

    /// Queued download finished.
    virtual void onQueueItemFinished(const std::string& target,
                                     int64_t size) {}

    /// Item removed from download queue.
    virtual void onQueueItemRemoved(const std::string& target) {}

    // =====================================================================
    // Hashing events
    // =====================================================================

    /// Hash progress update (called periodically).
    virtual void onHashProgress(const std::string& currentFile,
                                uint64_t bytesLeft,
                                size_t filesLeft) {}
};

} // namespace eiskaltdcpp_py
