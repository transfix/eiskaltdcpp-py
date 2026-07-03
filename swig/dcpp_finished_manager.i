/*
 * dcpp_finished_manager.i — FinishedManager SWIG wrapping
 *
 * Completed transfer history: query by file/user, remove entries.
 */

%{
#include <dcpp/FinishedManager.h>
#include <dcpp/FinishedItem.h>
using dcpp::FinishedManager;
using dcpp::FinishedItem;
using dcpp::FinishedFileItemPtr;
using dcpp::FinishedUserItemPtr;
%}

%nodefaultctor dcpp::FinishedManager;

namespace dcpp {

class FinishedManager : public ContextAware {
public:
    void remove(bool upload, const std::string& file);
    void remove(bool upload, const HintedUser& user);
    void removeAll(bool upload);

    std::string getTarget(const std::string& aTTH);
};

}  // namespace dcpp

%extend dcpp::FinishedManager {
    std::string __str__() {
        return "FinishedManager()";
    }
}
