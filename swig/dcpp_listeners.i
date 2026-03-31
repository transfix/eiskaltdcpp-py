/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * dcpp_listeners.i — SWIG director wrapping for Python listener adapters.
 *
 * Each PyXxxListener adapter class gets %feature("director") so Python
 * subclasses can override the named virtual methods and receive dcpp events.
 * SWIG directors + threads="1" ensure proper GIL handling.
 *
 * Usage in Python:
 *
 *   class MyQueueListener(dc_core.PyQueueManagerListener):
 *       def onAdded(self, target, size, tth):
 *           print(f"Queued: {target}")
 *       def onFinished(self, target, size, dir):
 *           print(f"Done: {target}")
 *
 *   listener = MyQueueListener()
 *   ctx.addQueueListener(listener)
 *   # ... later ...
 *   ctx.removeQueueListener(listener)
 */

// Header needed for SWIG wrapper compilation
%{
#include "listener_adapters.h"
%}

// ============================================================================
// Enable directors for all adapter classes
// ============================================================================

%feature("director") eiskaltdcpp_py::PyClientListener;
%feature("director") eiskaltdcpp_py::PyClientManagerListener;
%feature("director") eiskaltdcpp_py::PySearchManagerListener;
%feature("director") eiskaltdcpp_py::PyQueueManagerListener;
%feature("director") eiskaltdcpp_py::PyDownloadManagerListener;
%feature("director") eiskaltdcpp_py::PyUploadManagerListener;
%feature("director") eiskaltdcpp_py::PyTimerManagerListener;

// ============================================================================
// Hide the protected on() dispatchers — Python users override named methods
// ============================================================================

%ignore eiskaltdcpp_py::PyClientListener::on;
%ignore eiskaltdcpp_py::PyClientManagerListener::on;
%ignore eiskaltdcpp_py::PySearchManagerListener::on;
%ignore eiskaltdcpp_py::PyQueueManagerListener::on;
%ignore eiskaltdcpp_py::PyDownloadManagerListener::on;
%ignore eiskaltdcpp_py::PyUploadManagerListener::on;
%ignore eiskaltdcpp_py::PyTimerManagerListener::on;

// ============================================================================
// Docstrings
// ============================================================================

%feature("docstring") eiskaltdcpp_py::PyClientListener "
Per-hub listener adapter. Override named methods to receive hub events.

Attach to a hub via ctx.addHubListener(hub_url, listener).
Detach via ctx.removeHubListener(hub_url, listener).

Methods: onConnecting, onConnected, onFailed, onRedirect, onGetPassword,
onHubUpdated, onNickTaken, onHubFull, onSearchFlood, onMessage,
onStatusMessage, onUserUpdated, onUsersUpdated, onUserRemoved,
onHubUserCommand.
";

%feature("docstring") eiskaltdcpp_py::PyClientManagerListener "
Global listener for user/hub lifecycle events across all hubs.

Attach via ctx.addClientManagerListener(listener).

Methods: onUserConnected, onUserUpdated, onUserDisconnected,
onIncomingSearch, onClientConnected, onClientUpdated, onClientDisconnected.
";

%feature("docstring") eiskaltdcpp_py::PySearchManagerListener "
Global listener for search result events.

Attach via ctx.addSearchListener(listener).

Methods: onSearchResult(result: SearchResultInfo).
";

%feature("docstring") eiskaltdcpp_py::PyQueueManagerListener "
Global listener for download queue events (all 18 dcpp events).

Attach via ctx.addQueueListener(listener).

Methods: onAdded, onFinished, onRemoved, onMoved, onSourcesUpdated,
onStatusUpdated, onSearchStringUpdated, onFileMoved, onRecheckStarted,
onRecheckNoFile, onRecheckFileTooSmall, onRecheckDownloadsRunning,
onRecheckNoTree, onRecheckAlreadyFinished, onRecheckDone, onCRCFailed,
onCRCChecked, onPartialList.
";

%feature("docstring") eiskaltdcpp_py::PyDownloadManagerListener "
Global listener for download transfer progress events.

Attach via ctx.addDownloadListener(listener).

Methods: onRequesting, onStarting, onTick, onComplete, onFailed.
";

%feature("docstring") eiskaltdcpp_py::PyUploadManagerListener "
Global listener for upload transfer progress events.

Attach via ctx.addUploadListener(listener).

Methods: onStarting, onTick, onComplete, onFailed,
onWaitingAddFile, onWaitingRemoveUser.
";

%feature("docstring") eiskaltdcpp_py::PyTimerManagerListener "
Global timer listener for periodic events.

Attach via ctx.addTimerListener(listener).

Methods: onSecond(tick), onMinute(tick).
Note: onSecond fires every second — use sparingly to avoid performance impact.
";

// ============================================================================
// Include the adapter header — generates Python wrappers
// ============================================================================

%include "listener_adapters.h"
