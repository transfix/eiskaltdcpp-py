/*
 * dcpp_search_manager.i — SearchManager SWIG wrapping
 *
 * Search operations: initiate searches, size/type modes.
 */

%{
#include <dcpp/SearchManager.h>
using dcpp::SearchManager;
%}

%nodefaultctor dcpp::SearchManager;

namespace dcpp {

class SearchManager : public ContextAware {
public:
    enum SizeModes {
        SIZE_DONTCARE = 0x00,
        SIZE_ATLEAST  = 0x01,
        SIZE_ATMOST   = 0x02
    };

    enum TypeModes {
        TYPE_ANY = 0,
        TYPE_AUDIO,
        TYPE_COMPRESSED,
        TYPE_DOCUMENT,
        TYPE_EXECUTABLE,
        TYPE_PICTURE,
        TYPE_VIDEO,
        TYPE_DIRECTORY,
        TYPE_TTH,
        TYPE_CD_IMAGE,
        TYPE_LAST
    };

    static const char* getTypeStr(int type);

    // ── Search ─────────────────────────────────────────────────
    void search(const std::string& aName, int64_t aSize,
                TypeModes aTypeMode, SizeModes aSizeMode,
                const std::string& aToken, void* aOwner = NULL);

    void search(const std::string& aName, const std::string& aSize,
                TypeModes aTypeMode, SizeModes aSizeMode,
                const std::string& aToken, void* aOwner = NULL);

    // ── Network ────────────────────────────────────────────────
    const std::string& getPort() const;
    void listen();
    void disconnect() noexcept;
};

}  // namespace dcpp

%extend dcpp::SearchManager {
    std::string __str__() {
        return "SearchManager()";
    }
}
