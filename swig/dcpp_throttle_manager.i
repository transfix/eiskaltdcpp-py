/*
 * dcpp_throttle_manager.i — ThrottleManager SWIG wrapping
 *
 * Bandwidth throttling control: get/set limits.
 */

%{
#include <dcpp/ThrottleManager.h>
using dcpp::ThrottleManager;
%}

%nodefaultctor dcpp::ThrottleManager;

namespace dcpp {

class ThrottleManager : public ContextAware {
public:
    int getUpLimit();
    int getDownLimit();

    void setSetting(SettingsManager::IntSetting setting, int value);
    SettingsManager::IntSetting getCurSetting(SettingsManager::IntSetting setting);

    void shutdown();
};

}  // namespace dcpp

%extend dcpp::ThrottleManager {
    std::string __str__() {
        return "ThrottleManager(up=" + std::to_string($self->getUpLimit()) +
               ", down=" + std::to_string($self->getDownLimit()) + ")";
    }

    %pythoncode %{
    @property
    def upload_limit(self):
        """Current upload limit in KiB/s (0 = unlimited)."""
        return self.getUpLimit()

    @property
    def download_limit(self):
        """Current download limit in KiB/s (0 = unlimited)."""
        return self.getDownLimit()
    %}
}
