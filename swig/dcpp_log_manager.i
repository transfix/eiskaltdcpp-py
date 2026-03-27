/*
 * dcpp_log_manager.i — LogManager SWIG wrapping
 *
 * Logging: log messages, get paths, recent entries.
 */

%{
#include <dcpp/LogManager.h>
using dcpp::LogManager;
%}

%nodefaultctor dcpp::LogManager;

namespace dcpp {

class LogManager : public ContextAware {
public:
    enum Area {
        CHAT, PM, DOWNLOAD, FINISHED_DOWNLOAD, UPLOAD,
        SYSTEM, STATUS, SPY, CMD_DEBUG, LAST
    };
    enum { FILE, FORMAT };

    void message(const std::string& msg);
    std::string getPath(Area area) const;

    const std::string& getSetting(int area, int sel) const;
    void saveSetting(int area, int sel, const std::string& setting);
};

}  // namespace dcpp

%extend dcpp::LogManager {
    std::string __str__() {
        return "LogManager()";
    }
}
