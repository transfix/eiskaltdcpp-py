/*
 * dcpp_upload_manager.i — UploadManager SWIG wrapping
 *
 * Upload monitoring: count, running average, slots, waiting users.
 */

%{
#include <dcpp/UploadManager.h>
using dcpp::UploadManager;
%}

%nodefaultctor dcpp::UploadManager;

namespace dcpp {

class UploadManager : public ContextAware {
public:
    size_t getUploadCount();
    int64_t getRunningAverage();
    uint8_t getSlots() const;
    int getFreeSlots();
    int getFreeExtraSlots();

    void reserveSlot(const HintedUser& aUser);
    HintedUserList getWaitingUsers() const;
    void clearUserFiles(const UserPtr&);
    void notifyQueuedUsers();

    void reloadRestrictions();
    void updateLimits();

    uint8_t getExtraPartial() const;
    uint8_t getExtra() const;
    uint64_t getLastGrant() const;
};

}  // namespace dcpp

%extend dcpp::UploadManager {
    std::string __str__() {
        return "UploadManager(count=" + std::to_string($self->getUploadCount()) +
               ", avg=" + std::to_string($self->getRunningAverage()) +
               ", free_slots=" + std::to_string($self->getFreeSlots()) + ")";
    }

    %pythoncode %{
    @property
    def count(self):
        """Number of active uploads."""
        return self.getUploadCount()

    @property
    def speed(self):
        """Running average upload speed in bytes/sec."""
        return self.getRunningAverage()

    @property
    def free_slots(self):
        """Number of free upload slots."""
        return self.getFreeSlots()
    %}
}
