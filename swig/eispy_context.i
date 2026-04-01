/*
 * eispy_context.i — EisPyContext extensions for direct manager access
 *
 * EisPyContext is the main Python-facing class — it handles:
 *   - Startup/shutdown sequencing
 *   - Listener multiplexing (BridgeListeners)
 *   - Hub cache (ABBA-deadlock-safe snapshots)
 *   - Chat/search result caches
 *   - Lua scripting bridge
 *
 * This file adds Python-friendly property access to EisPyContext's
 * underlying DCContext, giving Python direct manager access while
 * keeping the orchestration/cache layer intact.
 */

// No new C++ code needed — EisPyContext already owns DCContext.
// We just need to expose the context pointer through SWIG.

%{
#include "eispy_context.h"
using eiskaltdcpp_py::EisPyContext;
%}

// Extend EisPyContext with a context accessor for direct manager access
%extend eiskaltdcpp_py::EisPyContext {
    // Return the raw DCContext* for direct manager access
    dcpp::DCContext* getContext() {
        // EisPyContext owns a unique_ptr<DCContext> m_context
        return dcpp::getContext();
    }

    %pythoncode %{
    @property
    def context(self):
        """Access the underlying DCContext for direct manager calls.

        Example:
            ctx = dc_core.EisPyContext()
            ctx.initialize('/tmp/config')
            settings = ctx.context.getSettingsManager()
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

    @property
    def connection_manager(self):
        """Direct access to ConnectionManager."""
        ctx = self.getContext()
        return ctx.getConnectionManager() if ctx else None

    @property
    def dyndns(self):
        """Direct access to DynDNS."""
        ctx = self.getContext()
        return ctx.getDynDNS() if ctx else None
    %}
}
