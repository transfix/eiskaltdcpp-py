/*
 * dcpp_queue_manager.i — QueueManager SWIG wrapping
 *
 * Download queue: add/remove/move items, set priority, lock/unlock.
 * Includes Python context manager for lockQueue()/unlockQueue().
 */

%{
#include <dcpp/QueueManager.h>
#include <dcpp/QueueItem.h>
using dcpp::QueueManager;
using dcpp::QueueItem;
%}

// ============================================================================
// QueueItem — expose priority enum and key fields
// ============================================================================

%nodefaultctor dcpp::QueueItem;

namespace dcpp {

class QueueItem {
public:
    enum Priority {
        DEFAULT = -1,
        PAUSED = 0,
        LOWEST,
        LOW,
        NORMAL,
        HIGH,
        HIGHEST
    };
};

}  // namespace dcpp

// ============================================================================
// QueueManager
// ============================================================================

%nodefaultctor dcpp::QueueManager;

namespace dcpp {

class QueueManager : public ContextAware {
public:
    // ── Add to queue ───────────────────────────────────────────
    void add(const std::string& aTarget, int64_t aSize, const TTHValue& root);
    void add(const std::string& aTarget, int64_t aSize, const TTHValue& root,
             const HintedUser& aUser, int aFlags = 0, bool addBad = true);
    void addList(const HintedUser& aUser, int aFlags,
                 const std::string& aInitialDir = "");
    void readd(const std::string& target, const HintedUser& aUser);

    // ── Queue operations ───────────────────────────────────────
    void move(const std::string& aSource, const std::string& aTarget) noexcept;
    void remove(const std::string& aTarget) noexcept;
    void removeSource(const std::string& aTarget, const UserPtr& aUser,
                      int reason, bool removeConn = true) noexcept;
    void removeSource(const UserPtr& aUser, int reason) noexcept;
    void recheck(const std::string& aTarget);

    // ── Priority ───────────────────────────────────────────────
    void setPriority(const std::string& aTarget, QueueItem::Priority p) noexcept;

    // ── Query ──────────────────────────────────────────────────
    StringList getTargets(const TTHValue& tth);
    int64_t getSize(const std::string& target) noexcept;
    int64_t getPos(const std::string& target) noexcept;
    int64_t getQueued(const UserPtr& aUser) const;
    QueueItem::Priority hasDownload(const UserPtr& aUser) noexcept;
    int countOnlineSources(const std::string& aTarget);

    // ── Matching ───────────────────────────────────────────────
    void matchAllListings();

    // ── Persistence ────────────────────────────────────────────
    void loadQueue() noexcept;
    void saveQueue(bool force = false) noexcept;

    // ── Partial search/result ──────────────────────────────────
    bool isChunkDownloaded(const TTHValue& tth, int64_t startPos,
                           int64_t& bytes, std::string& tempTarget, int64_t& size);
};

}  // namespace dcpp

%extend dcpp::QueueManager {
    std::string __str__() {
        return "QueueManager()";
    }

    %pythoncode %{
    class _QueueLock:
        """Context manager for lockQueue()/unlockQueue()."""
        def __init__(self, qm):
            self._qm = qm
        def __enter__(self):
            return self._qm.lockQueue()
        def __exit__(self, *args):
            self._qm.unlockQueue()

    def locked(self):
        """Return a context manager that holds the queue lock.

        Usage:
            with queue_manager.locked() as queue:
                # queue is locked, safe to iterate
                pass
            # automatically unlocked
        """
        return self._QueueLock(self)
    %}
}
