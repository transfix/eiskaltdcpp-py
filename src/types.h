/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * Copyright (C) 2026 Verlihub Team
 * Licensed under GPL-3.0-or-later
 *
 * types.h — Data transfer structs exposed to Python via SWIG.
 */

#pragma once

#include <string>
#include <cstdint>
#include <vector>

namespace eiskaltdcpp_py {

/// Information about a connected hub.
struct HubInfo {
    std::string url;
    std::string name;
    std::string description;
    int userCount = 0;
    int64_t sharedBytes = 0;
    bool connected = false;
    bool isOp = false;
    bool isSecure = false;         ///< TLS-encrypted connection to hub
    bool isTrusted = false;        ///< Hub TLS certificate is trusted
    std::string cipherName;        ///< TLS cipher in use (empty if not TLS)
};

/// Information about a hub user.
struct UserInfo {
    std::string nick;
    std::string description;
    std::string connection;
    std::string email;
    std::string cid;
    int64_t shareSize = 0;
    bool isOp = false;
    bool isBot = false;
};

/// A search result.
struct SearchResultInfo {
    std::string file;
    int64_t size = 0;
    std::string tth;
    std::string nick;
    std::string hubUrl;
    std::string hubName;
    int freeSlots = 0;
    int totalSlots = 0;
    bool isDirectory = false;
};

/// An item in the download queue.
struct QueueItemInfo {
    std::string target;
    std::string filename;
    int64_t size = 0;
    int64_t downloadedBytes = 0;
    std::string tth;
    int priority = 3;         // 0=paused, 1=lowest .. 5=highest
    int sources = 0;
    int onlineSources = 0;
    int status = 0;           // 0=queued, 1=running, 2=finished
};

/// An active transfer (upload or download).
struct TransferInfo {
    std::string filename;
    std::string nick;
    std::string hubUrl;
    int64_t size = 0;
    int64_t pos = 0;
    int64_t speed = 0;        // bytes/sec
    bool isDownload = true;
};

/// A shared directory.
struct ShareDirInfo {
    std::string realPath;
    std::string virtualName;
    int64_t size = 0;
};

/// File hashing status.
struct HashStatus {
    std::string currentFile;
    uint64_t bytesLeft = 0;
    size_t filesLeft = 0;
    bool paused = false;
};

/// An entry in a browsed file list.
struct FileListEntry {
    std::string name;
    int64_t size = 0;
    std::string tth;            // empty for directories
    bool isDirectory = false;
};

/// Aggregate transfer statistics.
struct TransferStats {
    int64_t downloadSpeed = 0;    // bytes/sec
    int64_t uploadSpeed = 0;      // bytes/sec
    int64_t totalDownloaded = 0;  // lifetime bytes
    int64_t totalUploaded = 0;    // lifetime bytes
    int downloadCount = 0;
    int uploadCount = 0;
};

// ===========================================================================
// NMDCpb Channels / Calls (Python-friendly snapshots)
// ===========================================================================

/// A member of an NMDCpb channel.
struct ChannelMemberInfo {
    std::string nick;
    int role = 0;               ///< 0=member,1=admin,2=owner,3=readonly
};

/// Result of generating a private-channel sender key. The key material is
/// hex-encoded (64 lowercase hex chars for the 32-byte key) so it maps to a
/// plain Python str; distribute it to channel members over E2EPM.
struct SenderKeyPy {
    std::string keyHex;         ///< 64-char hex of the 32-byte key ("" on failure)
    uint32_t keyId = 0;
    uint32_t generation = 0;
};

/// Snapshot of an NMDCpb channel from the client-side registry.
struct ChannelInfoPy {
    std::string channelId;
    std::string name;
    std::string topic;
    bool isPrivate = false;
    std::string ownerNick;
    uint64_t createdAt = 0;
    uint32_t memberCount = 0;
    bool joined = false;
    std::vector<ChannelMemberInfo> members;
};

/// Snapshot of an NMDCpb voice/video call from the client-side registry.
struct CallInfoPy {
    std::string callId;
    std::string peerNick;
    bool isGroup = false;
    std::string groupId;
    std::vector<int> media;     ///< 0=audio,1=video,2=screen-share
    int state = 0;              ///< 0=ringing-out,1=ringing-in,2=active,3=ended
    uint64_t createdAt = 0;
    uint64_t answeredAt = 0;
    bool localAudioMuted = false;
    bool localVideoMuted = false;
    bool localScreenSharing = false;
    bool remoteAudioMuted = false;
    bool remoteVideoMuted = false;
    bool remoteScreenSharing = false;
};

} // namespace eiskaltdcpp_py

