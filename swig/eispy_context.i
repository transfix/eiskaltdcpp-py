/*
 * eispy_context.i — EisPyContext wrapping (thin lifecycle wrapper)
 *
 * EisPyContext replaces DCBridge for new code — it handles:
 *   - Startup/shutdown sequencing
 *   - Listener multiplexing (BridgeListeners)
 *   - Hub cache (ABBA-deadlock-safe snapshots)
 *   - Chat/search result caches
 *   - Lua scripting bridge
 *
 * For Phase 1, EisPyContext IS DCBridge — we expose it under both names.
 * The existing DCBridge class continues to work alongside the new
 * direct manager access. In Phase 3, DCBridge will be removed.
 *
 * This file adds Python-friendly property access to DCBridge's
 * underlying DCContext, giving Python direct manager access while
 * keeping the orchestration/cache layer intact.
 */

// No new C++ code needed for Phase 1 — DCBridge already owns DCContext.
// We just need to expose the context pointer through SWIG.

%{
#include "bridge.h"
using eiskaltdcpp_py::DCBridge;
%}

// Extend DCBridge with a context accessor for direct manager access
%extend eiskaltdcpp_py::DCBridge {
    // Return the raw DCContext* for direct manager access
    dcpp::DCContext* getContext() {
        // DCBridge owns a unique_ptr<DCContext> m_context
        // We access it through a public method we'll need to add,
        // or we use the fact that DCBridge already has the context
        // For now, we expose it via the module-level getContext()
        return dcpp::getContext();
    }

    %pythoncode %{
    @property
    def context(self):
        """Access the underlying DCContext for direct manager calls.

        Example:
            bridge = dc_core.DCBridge()
            bridge.initialize('/tmp/config')
            settings = bridge.context.getSettingsManager()
            nick = settings.get(dc_core.SettingsManager.NICK)
        """
        return self.getContext()

    @property
    def settings_manager(self):
        """Direct access to SettingsManager."""
        ctx = self.getContext()
        return ctx.getSettingsManager() if ctx else None

    @property
    def client_manager(self):
        """Direct access to ClientManager."""
        ctx = self.getContext()
        return ctx.getClientManager() if ctx else None

    @property
    def queue_manager(self):
        """Direct access to QueueManager."""
        ctx = self.getContext()
        return ctx.getQueueManager() if ctx else None

    @property
    def share_manager(self):
        """Direct access to ShareManager."""
        ctx = self.getContext()
        return ctx.getShareManager() if ctx else None

    @property
    def search_manager(self):
        """Direct access to SearchManager."""
        ctx = self.getContext()
        return ctx.getSearchManager() if ctx else None

    @property
    def hash_manager(self):
        """Direct access to HashManager."""
        ctx = self.getContext()
        return ctx.getHashManager() if ctx else None

    @property
    def download_manager(self):
        """Direct access to DownloadManager."""
        ctx = self.getContext()
        return ctx.getDownloadManager() if ctx else None

    @property
    def upload_manager(self):
        """Direct access to UploadManager."""
        ctx = self.getContext()
        return ctx.getUploadManager() if ctx else None

    @property
    def throttle_manager(self):
        """Direct access to ThrottleManager."""
        ctx = self.getContext()
        return ctx.getThrottleManager() if ctx else None

    @property
    def favorite_manager(self):
        """Direct access to FavoriteManager."""
        ctx = self.getContext()
        return ctx.getFavoriteManager() if ctx else None

    @property
    def finished_manager(self):
        """Direct access to FinishedManager."""
        ctx = self.getContext()
        return ctx.getFinishedManager() if ctx else None

    @property
    def connectivity_manager(self):
        """Direct access to ConnectivityManager."""
        ctx = self.getContext()
        return ctx.getConnectivityManager() if ctx else None

    @property
    def mapping_manager(self):
        """Direct access to MappingManager."""
        ctx = self.getContext()
        return ctx.getMappingManager() if ctx else None

    @property
    def crypto_manager(self):
        """Direct access to CryptoManager."""
        ctx = self.getContext()
        return ctx.getCryptoManager() if ctx else None

    @property
    def log_manager(self):
        """Direct access to LogManager."""
        ctx = self.getContext()
        return ctx.getLogManager() if ctx else None

    @property
    def adl_search_manager(self):
        """Direct access to ADLSearchManager."""
        ctx = self.getContext()
        return ctx.getADLSearchManager() if ctx else None

    @property
    def debug_manager(self):
        """Direct access to DebugManager."""
        ctx = self.getContext()
        return ctx.getDebugManager() if ctx else None

    @property
    def ip_filter(self):
        """Direct access to IPFilter."""
        ctx = self.getContext()
        return ctx.getIPFilter() if ctx else None
    %}
}
