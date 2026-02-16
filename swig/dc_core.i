/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * dc_core.i — Master SWIG interface file.
 *
 * Follows the pattern established in verlihub's verlihub_core.i:
 *   - directors="1" for C++ → Python callbacks
 *   - threads="1" for auto GIL release during C++ calls
 *   - %exception block for C++ → Python exception conversion
 *   - %feature("director") for callback class
 *   - %extend for Python-friendly additions
 */

%module(directors="1", threads="1") dc_core

// Standard SWIG includes
%include <std_string.i>
%include <std_vector.i>
%include <exception.i>
%include <stdint.i>

// Enable thread support — release GIL during C++ calls
%thread;

// ============================================================================
// Exception handling — convert C++ exceptions to Python exceptions
// ============================================================================

%exception {
    try {
        $action
    } catch (const std::exception& e) {
        SWIG_exception(SWIG_RuntimeError, e.what());
    } catch (...) {
        SWIG_exception(SWIG_UnknownError, "Unknown C++ exception");
    }
}

// ============================================================================
// C++ headers needed for compilation (the %{ %} block)
// ============================================================================

%{
#include "types.h"
#include "callbacks.h"
#include "bridge.h"

using namespace eiskaltdcpp_py;
%}

// ============================================================================
// Standard library template instantiations
// ============================================================================

namespace std {
    %template(StringVector)         vector<string>;
    %template(UserInfoVector)       vector<eiskaltdcpp_py::UserInfo>;
    %template(SearchResultVector)   vector<eiskaltdcpp_py::SearchResultInfo>;
    %template(QueueItemVector)      vector<eiskaltdcpp_py::QueueItemInfo>;
    %template(HubInfoVector)        vector<eiskaltdcpp_py::HubInfo>;
    %template(ShareDirVector)       vector<eiskaltdcpp_py::ShareDirInfo>;
    %template(FileListEntryVector)  vector<eiskaltdcpp_py::FileListEntry>;
    %template(TransferInfoVector)   vector<eiskaltdcpp_py::TransferInfo>;
}

// ============================================================================
// DCClientCallback — Director class for Python callbacks
// ============================================================================

/*
 * Enable directors for DCClientCallback.
 *
 * This allows Python classes to inherit from DCClientCallback and
 * override virtual methods that will be called from C++ threads.
 * SWIG directors automatically acquire the GIL when calling into Python.
 *
 * Example Python usage:
 *
 *   class MyCallback(dc_core.DCClientCallback):
 *       def onHubConnected(self, hub_url, hub_name):
 *           print(f"Connected to {hub_name} ({hub_url})")
 *
 *       def onChatMessage(self, hub_url, nick, message):
 *           print(f"<{nick}> {message}")
 *
 *       def onSearchResult(self, result):
 *           print(f"Found: {result.file} ({result.size} bytes)")
 *
 *       def onDownloadComplete(self, transfer):
 *           print(f"Downloaded: {transfer.filename}")
 */
%feature("director") eiskaltdcpp_py::DCClientCallback;

// Director exception handling
%feature("director:except") {
    if ($error != NULL) {
        throw Swig::DirectorMethodException();
    }
}

// ============================================================================
// Data structs — expose with Python-friendly features
// ============================================================================

%feature("autodoc", "1");

// --- HubInfo ---
%feature("python:slot", "tp_str", functype="reprfunc") eiskaltdcpp_py::HubInfo::__str__;
%extend eiskaltdcpp_py::HubInfo {
    std::string __str__() {
        return "HubInfo(name='" + $self->name + "', url='" + $self->url +
               "', users=" + std::to_string($self->userCount) +
               ", connected=" + ($self->connected ? "True" : "False") + ")";
    }
    std::string __repr__() {
        return "HubInfo(name='" + $self->name + "', url='" + $self->url + "')";
    }
}

// --- UserInfo ---
%feature("python:slot", "tp_str", functype="reprfunc") eiskaltdcpp_py::UserInfo::__str__;
%extend eiskaltdcpp_py::UserInfo {
    std::string __str__() {
        return "UserInfo(nick='" + $self->nick +
               "', share=" + std::to_string($self->shareSize) +
               ", op=" + ($self->isOp ? "True" : "False") + ")";
    }
    std::string __repr__() {
        return "UserInfo(nick='" + $self->nick + "')";
    }
}

// --- SearchResultInfo ---
%feature("python:slot", "tp_str", functype="reprfunc") eiskaltdcpp_py::SearchResultInfo::__str__;
%extend eiskaltdcpp_py::SearchResultInfo {
    std::string __str__() {
        return "SearchResult(file='" + $self->file +
               "', size=" + std::to_string($self->size) +
               ", nick='" + $self->nick +
               "', slots=" + std::to_string($self->freeSlots) +
               "/" + std::to_string($self->totalSlots) + ")";
    }
}

// --- QueueItemInfo ---
%feature("python:slot", "tp_str", functype="reprfunc") eiskaltdcpp_py::QueueItemInfo::__str__;
%extend eiskaltdcpp_py::QueueItemInfo {
    std::string __str__() {
        return "QueueItem(target='" + $self->target +
               "', size=" + std::to_string($self->size) +
               ", downloaded=" + std::to_string($self->downloadedBytes) + ")";
    }
}

// --- TransferInfo ---
%feature("python:slot", "tp_str", functype="reprfunc") eiskaltdcpp_py::TransferInfo::__str__;
%extend eiskaltdcpp_py::TransferInfo {
    std::string __str__() {
        std::string dir = $self->isDownload ? "DL" : "UL";
        return "Transfer(" + dir + " '" + $self->filename +
               "', " + std::to_string($self->pos) +
               "/" + std::to_string($self->size) +
               ", speed=" + std::to_string($self->speed) + ")";
    }
}

// --- TransferStats ---
%feature("python:slot", "tp_str", functype="reprfunc") eiskaltdcpp_py::TransferStats::__str__;
%extend eiskaltdcpp_py::TransferStats {
    std::string __str__() {
        return "TransferStats(dl_speed=" + std::to_string($self->downloadSpeed) +
               ", ul_speed=" + std::to_string($self->uploadSpeed) +
               ", dl_count=" + std::to_string($self->downloadCount) +
               ", ul_count=" + std::to_string($self->uploadCount) + ")";
    }
}

// --- HashStatus ---
%feature("python:slot", "tp_str", functype="reprfunc") eiskaltdcpp_py::HashStatus::__str__;
%extend eiskaltdcpp_py::HashStatus {
    std::string __str__() {
        return "HashStatus(files_left=" + std::to_string($self->filesLeft) +
               ", bytes_left=" + std::to_string($self->bytesLeft) +
               ", current='" + $self->currentFile + "')";
    }
}

// ============================================================================
// DCBridge — Main API class
// ============================================================================

%feature("docstring") eiskaltdcpp_py::DCBridge "
Main bridge class providing access to the eiskaltdcpp DC client core.

Lifecycle:
    1. Construct a DCBridge instance
    2. Call initialize(config_dir) to start the core
    3. Call setCallback(handler) to receive events
    4. Use connectHub(), search(), addToQueue(), etc.
    5. Call shutdown() when done

Thread safety:
    All methods are thread-safe. The DC core runs its own threads internally.
    Callback dispatch to Python acquires the GIL automatically via SWIG directors.

Example:
    bridge = dc_core.DCBridge()
    bridge.initialize('/tmp/dc-config')

    class MyHandler(dc_core.DCClientCallback):
        def onChatMessage(self, hub_url, nick, message):
            print(f'<{nick}> {message}')

    handler = MyHandler()
    bridge.setCallback(handler)
    bridge.connectHub('dchub://example.com:411')
";

// Ignore internal/private members
%ignore eiskaltdcpp_py::DCBridge::HubData;
%ignore eiskaltdcpp_py::DCBridge::findHub;
%ignore eiskaltdcpp_py::DCBridge::findClient;
%ignore eiskaltdcpp_py::DCBridge::startNetworking;

// ============================================================================
// Include the headers to generate wrappers
// ============================================================================

%include "types.h"
%include "callbacks.h"
%include "bridge.h"

// ============================================================================
// Python-friendly extensions to DCBridge
// ============================================================================

%extend eiskaltdcpp_py::DCBridge {
    /*
     * Python context manager support (with statement).
     *
     * Example:
     *   bridge = dc_core.DCBridge()
     *   bridge.initialize('/tmp/config')
     *   with bridge:
     *       bridge.connectHub('dchub://example.com')
     *       # ... use the client ...
     *   # shutdown() called automatically
     */
    PyObject* __enter__() {
        Py_INCREF($self);
        return SWIG_NewPointerObj($self, SWIGTYPE_p_eiskaltdcpp_py__DCBridge, 0);
    }

    void __exit__(PyObject* exc_type, PyObject* exc_val, PyObject* exc_tb) {
        if ($self->isInitialized()) {
            $self->shutdown();
        }
    }

    %pythoncode %{
    @property
    def initialized(self):
        """Whether the DC core has been initialized."""
        return self.isInitialized()

    @property
    def version(self):
        """Get libeiskaltdcpp version string."""
        return DCBridge.getVersion()

    @property
    def hubs(self):
        """List of currently connected/configured hubs."""
        return self.listHubs()

    @property
    def share_size(self):
        """Total share size in bytes."""
        return self.getShareSize()

    @property
    def shared_files(self):
        """Total number of shared files."""
        return self.getSharedFileCount()

    @property
    def transfer_stats(self):
        """Current transfer statistics."""
        return self.getTransferStats()

    @property
    def hash_status(self):
        """Current file hashing status."""
        return self.getHashStatus()
    %}
}
