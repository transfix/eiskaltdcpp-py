/*
 * dcpp_context.i — DCContext class + startup/getContext/setContext
 *
 * Wraps the application context that owns all core manager instances.
 * Manager accessor methods return non-owning raw pointers — SWIG must
 * NOT take ownership (no %newobject on getters).
 *
 * IMPORTANT: This file must be included AFTER all manager .i files
 * so that SWIG can properly type the returned pointers. ContextAware
 * (needed by managers) is in dcpp_context_base.i which comes first.
 */

%{
#include <dcpp/DCPlusPlus.h>
#include <dcpp/DCContext.h>
#include <dcpp/SettingsManager.h>
#include <dcpp/ClientManager.h>
#include <dcpp/QueueManager.h>
#include <dcpp/ShareManager.h>
#include <dcpp/SearchManager.h>
#include <dcpp/HashManager.h>
#include <dcpp/DownloadManager.h>
#include <dcpp/UploadManager.h>
#include <dcpp/ThrottleManager.h>
#include <dcpp/FavoriteManager.h>
#include <dcpp/FinishedManager.h>
#include <dcpp/ConnectivityManager.h>
#include <dcpp/MappingManager.h>
#include <dcpp/CryptoManager.h>
#include <dcpp/LogManager.h>
#include <dcpp/TimerManager.h>
#include <dcpp/ADLSearch.h>
#include <dcpp/DebugManager.h>
#include <dcpp/ResourceManager.h>
#include "extra/ipfilter.h"
%}

// ============================================================================
// DCContext — application context owning all managers
// ============================================================================

// Don't let Python delete DCContext through raw pointers from getContext()
%nodefaultdtor dcpp::DCContext;

namespace dcpp {

class DCContext {
public:
    DCContext();
    ~DCContext();

    void startup();
    void startupMinimal();
    void shutdown();
    bool isRunning() const noexcept;

    // ── Manager accessors (non-owning raw pointers) ──
    SettingsManager*     getSettingsManager()     const noexcept;
    ClientManager*       getClientManager()       const noexcept;
    QueueManager*        getQueueManager()        const noexcept;
    ShareManager*        getShareManager()        const noexcept;
    SearchManager*       getSearchManager()       const noexcept;
    HashManager*         getHashManager()         const noexcept;
    DownloadManager*     getDownloadManager()     const noexcept;
    UploadManager*       getUploadManager()       const noexcept;
    ThrottleManager*     getThrottleManager()     const noexcept;
    FavoriteManager*     getFavoriteManager()     const noexcept;
    FinishedManager*     getFinishedManager()     const noexcept;
    ConnectivityManager* getConnectivityManager() const noexcept;
    MappingManager*      getMappingManager()      const noexcept;
    CryptoManager*       getCryptoManager()       const noexcept;
    LogManager*          getLogManager()          const noexcept;
    TimerManager*        getTimerManager()        const noexcept;
    ADLSearchManager*    getADLSearchManager()    const noexcept;
    DebugManager*        getDebugManager()        const noexcept;
    ResourceManager*     getResourceManager()     const noexcept;
};

}  // namespace dcpp

// IPFilter is in global namespace — expose via %extend
%extend dcpp::DCContext {
    ::IPFilter* getIPFilter() {
        return $self->getIPFilter();
    }
}

%extend dcpp::DCContext {
    std::string __str__() {
        return std::string("DCContext(running=") +
               ($self->isRunning() ? "True" : "False") + ")";
    }
    std::string __repr__() {
        return "DCContext()";
    }
}

// ============================================================================
// Free functions: startup / getContext / setContext
// ============================================================================

// startup() returns unique_ptr<DCContext> — need typemap to transfer ownership
%ignore dcpp::startup;

namespace dcpp {
    DCContext* getContext() noexcept;
    void setContext(DCContext* ctx) noexcept;
}

// Provide a Python-friendly startup wrapper that returns a raw pointer
// The unique_ptr is captured in a static so it lives until dcpp_shutdown().
%inline %{
namespace {
    static std::unique_ptr<dcpp::DCContext> s_owned_context;
}

namespace dcpp {
    DCContext* dcpp_startup() {
        s_owned_context = dcpp::startup(nullptr, nullptr);
        return s_owned_context.get();
    }

    void dcpp_shutdown() {
        if (s_owned_context) {
            s_owned_context->shutdown();
            s_owned_context.reset();
        }
    }
}
%}
