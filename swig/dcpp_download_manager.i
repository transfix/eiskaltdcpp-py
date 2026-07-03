/*
 * dcpp_download_manager.i — DownloadManager SWIG wrapping
 *
 * Download monitoring: count, running average, start control.
 */

%{
#include <dcpp/DownloadManager.h>
using dcpp::DownloadManager;
%}

%nodefaultctor dcpp::DownloadManager;

namespace dcpp {

class DownloadManager : public ContextAware {
public:
    int64_t getRunningAverage();
    size_t getDownloadCount();
    bool startDownload(QueueItem::Priority prio);
};

}  // namespace dcpp

%extend dcpp::DownloadManager {
    std::string __str__() {
        return "DownloadManager(count=" + std::to_string($self->getDownloadCount()) +
               ", avg=" + std::to_string($self->getRunningAverage()) + ")";
    }

    %pythoncode %{
    @property
    def count(self):
        """Number of active downloads."""
        return self.getDownloadCount()

    @property
    def speed(self):
        """Running average download speed in bytes/sec."""
        return self.getRunningAverage()
    %}
}
