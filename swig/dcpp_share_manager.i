/*
 * dcpp_share_manager.i — ShareManager SWIG wrapping
 *
 * Share management: add/remove/rename directories, refresh, search, stats.
 */

%{
#include <dcpp/ShareManager.h>
using dcpp::ShareManager;
%}

%nodefaultctor dcpp::ShareManager;

namespace dcpp {

class ShareManager : public ContextAware {
public:
    // ── Directory management ───────────────────────────────────
    void addDirectory(const std::string& realPath, const std::string& virtualName);
    void removeDirectory(const std::string& realPath);
    void renameDirectory(const std::string& realPath, const std::string& virtualName);

    // ── Refresh ────────────────────────────────────────────────
    bool isRefreshing();
    void refresh(bool dirs = false, bool aUpdate = true, bool block = false) noexcept;
    void setDirty();

    // ── Path resolution ────────────────────────────────────────
    std::string toVirtual(const TTHValue& tth) const;
    std::string toReal(const std::string& virtualFile);
    StringList getRealPaths(const std::string& virtualPath);
    TTHValue getTTH(const std::string& virtualFile) const;

    // ── Directory listing ──────────────────────────────────────
    StringPairList getDirectories() const noexcept;

    // ── Statistics ─────────────────────────────────────────────
    int64_t getShareSize() const noexcept;
    int64_t getShareSize(const std::string& realPath) const noexcept;
    size_t getSharedFiles() const noexcept;
    std::string getShareSizeString() const;
    std::string getShareSizeString(const std::string& aDir) const;

    // ── TTH ────────────────────────────────────────────────────
    bool isTTHShared(const TTHValue& tth);

    // ── Validation ─────────────────────────────────────────────
    std::string validateVirtual(const std::string& aVirt) const noexcept;
    bool hasVirtual(const std::string& name) const noexcept;

    // ── Stats ──────────────────────────────────────────────────
    void addHits(uint32_t aHits);
    uint32_t getHits() const;
};

}  // namespace dcpp

%extend dcpp::ShareManager {
    std::string __str__() {
        return "ShareManager(size=" + std::to_string($self->getShareSize()) +
               ", files=" + std::to_string($self->getSharedFiles()) + ")";
    }

    %pythoncode %{
    @property
    def size(self):
        """Total share size in bytes."""
        return self.getShareSize()

    @property
    def file_count(self):
        """Total number of shared files."""
        return self.getSharedFiles()

    @property
    def directories(self):
        """List of shared directories as (real_path, virtual_name) pairs."""
        return self.getDirectories()
    %}
}
