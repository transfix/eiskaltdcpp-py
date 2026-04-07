/*
 * dcpp_hash_manager.i — HashManager SWIG wrapping
 *
 * File hashing: TTH computation, pause/resume, stats.
 */

%{
#include <dcpp/HashManager.h>
using dcpp::HashManager;
%}

%nodefaultctor dcpp::HashManager;

namespace dcpp {

class HashManager : public ContextAware {
public:
    // ── Hashing control ────────────────────────────────────────
    void stopHashing(const std::string& baseDir);
    bool pauseHashing() noexcept;
    void resumeHashing() noexcept;
    bool isHashingPaused() const noexcept;

    // ── TTH operations ─────────────────────────────────────────
    bool checkTTH(const std::string& aFileName, int64_t aSize, uint32_t aTimeStamp);
    TTHValue getTTH(const std::string& aFileName, int64_t aSize);

    // ── Tree operations ────────────────────────────────────────
    int64_t getBlockSize(const TTHValue& root);

    // ── Stats ──────────────────────────────────────────────────
    void getStats(std::string& curFile, uint64_t& bytesLeft, size_t& filesLeft) const;

    // ── Maintenance ────────────────────────────────────────────
    void rebuild();
    void startup();
    void shutdown();
};

}  // namespace dcpp

%extend dcpp::HashManager {
    std::string __str__() {
        return "HashManager(paused=" +
               std::string($self->isHashingPaused() ? "True" : "False") + ")";
    }

    // Convenience method returning stats as a tuple
    %pythoncode %{
    def stats(self):
        """Return (current_file, bytes_left, files_left) tuple."""
        import ctypes
        # Use the C++ getStats via output params — wrapped as tuple
        return self._get_stats_tuple()
    %}
}
