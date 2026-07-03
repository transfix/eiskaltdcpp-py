/*
 * dcpp_context_base.i — ContextAware base class + forward declarations
 *
 * This file is included BEFORE manager .i files so that managers
 * can inherit from ContextAware. The full DCContext class (with
 * manager accessor methods) is in dcpp_context.i and included AFTER
 * all manager classes, so SWIG can properly type the return pointers.
 */

%{
#include <dcpp/DCPlusPlus.h>
#include <dcpp/DCContext.h>
#include <dcpp/TimerManager.h>
#include <dcpp/ResourceManager.h>

using dcpp::DCContext;
%}

// ============================================================================
// Forward declarations for managers not exposed in detail
// ============================================================================

namespace dcpp {
    class TimerManager;
    class ResourceManager;
}

// ============================================================================
// ContextAware — mixin base with ctx() accessor
// ============================================================================

%nodefaultctor dcpp::ContextAware;
%nodefaultdtor dcpp::ContextAware;

namespace dcpp {

class ContextAware {
public:
    DCContext& ctx() const noexcept;
protected:
    // Constructor not exposed — base class only
};

}  // namespace dcpp

// Managers not exposed in detail — just forward-declared for getter returns
%nodefaultctor dcpp::TimerManager;
%nodefaultctor dcpp::ResourceManager;
namespace dcpp {
    class TimerManager {};
    class ResourceManager {};
}
