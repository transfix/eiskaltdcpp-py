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

} // namespace eiskaltdcpp_py
