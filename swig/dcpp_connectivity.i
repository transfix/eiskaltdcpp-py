/*
 * dcpp_connectivity.i — ConnectivityManager + MappingManager SWIG wrapping
 *
 * Connection detection, port mapping (UPnP).
 */

%{
#include <dcpp/ConnectivityManager.h>
#include <dcpp/MappingManager.h>
using dcpp::ConnectivityManager;
using dcpp::MappingManager;
%}

%nodefaultctor dcpp::ConnectivityManager;
%nodefaultctor dcpp::MappingManager;

namespace dcpp {

class ConnectivityManager : public ContextAware {
public:
    void detectConnection();
    void setup(bool settingsChanged);
    bool isRunning() const;
    void updateLast();
};

class MappingManager : public ContextAware {
public:
    bool open();
    void close();
    bool getOpened() const;
};

}  // namespace dcpp

%extend dcpp::ConnectivityManager {
    std::string __str__() {
        return "ConnectivityManager(running=" +
               std::string($self->isRunning() ? "True" : "False") + ")";
    }
}

%extend dcpp::MappingManager {
    std::string __str__() {
        return "MappingManager(opened=" +
               std::string($self->getOpened() ? "True" : "False") + ")";
    }
}
