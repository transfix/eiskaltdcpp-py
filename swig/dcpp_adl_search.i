/*
 * dcpp_adl_search.i — ADLSearchManager SWIG wrapping
 *
 * ADL (Automatic Directory Listing) search management.
 */

%{
#include <dcpp/ADLSearch.h>
using dcpp::ADLSearch;
using dcpp::ADLSearchManager;
%}

namespace dcpp {

class ADLSearch {
public:
    enum SourceType { TypeFirst = 0, OnlyFile = TypeFirst, OnlyDirectory, FullPath, TypeLast };
    enum SizeType { SizeBytes = TypeFirst, SizeKibiBytes, SizeMebiBytes, SizeGibiBytes };

    ADLSearch();

    std::string searchString;
    bool isActive;
    bool isAutoQueue;
    SourceType sourceType;
    int64_t minFileSize;
    int64_t maxFileSize;
    SizeType typeFileSize;
    std::string destDir;
    unsigned long ddIndex;

    SourceType StringToSourceType(const std::string& s);
    std::string SourceTypeToString(SourceType t);
    SizeType StringToSizeType(const std::string& s);
    std::string SizeTypeToString(SizeType t);
    int64_t GetSizeBase();
};

}  // namespace dcpp

%nodefaultctor dcpp::ADLSearchManager;

namespace dcpp {

class ADLSearchManager : public ContextAware {
public:
    typedef std::vector<ADLSearch> SearchCollection;

    SearchCollection collection;

    void load();
    void save();

    bool getBreakOnFirst() const;
    void setBreakOnFirst(bool);
};

}  // namespace dcpp

%extend dcpp::ADLSearch {
    std::string __str__() {
        return "ADLSearch('" + $self->searchString + "', active=" +
               ($self->isActive ? "True" : "False") + ")";
    }
}

%extend dcpp::ADLSearchManager {
    std::string __str__() {
        return "ADLSearchManager(entries=" +
               std::to_string($self->collection.size()) + ")";
    }
}

// Template for ADLSearch vector
namespace std {
    %template(ADLSearchList) vector<dcpp::ADLSearch>;
}
