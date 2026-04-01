/*
 * dcpp_dyndns.i — DynDNS SWIG wrapping
 *
 * Dynamic DNS update service — resolves the external IP address
 * using configured DynDNS providers.
 */

%{
#include "extra/dyndns.h"
using dcpp::DynDNS;
%}

%nodefaultctor dcpp::DynDNS;

namespace dcpp {

class DynDNS : public ContextAware {
public:
    void load();
    void stop();
};

}  // namespace dcpp

%extend dcpp::DynDNS {
    std::string __str__() {
        return "DynDNS()";
    }
}
