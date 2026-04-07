/*
 * dcpp_debug_manager.i — DebugManager SWIG wrapping
 *
 * Debug message dispatch for protocol debugging.
 */

%{
#include <dcpp/DebugManager.h>
using dcpp::DebugManager;
%}

%nodefaultctor dcpp::DebugManager;

namespace dcpp {

class DebugManager : public ContextAware {
public:
    enum { HUB_IN, HUB_OUT, CLIENT_IN, CLIENT_OUT };

    void SendCommandMessage(const std::string& mess, int typeDir, const std::string& ip);
    void SendDetectionMessage(const std::string& mess);
};

}  // namespace dcpp

%extend dcpp::DebugManager {
    std::string __str__() {
        return "DebugManager()";
    }
}
