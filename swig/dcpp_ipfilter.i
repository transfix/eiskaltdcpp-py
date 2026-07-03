/*
 * dcpp_ipfilter.i — IPFilter SWIG wrapping
 *
 * IP filtering rules: add/remove/check/import/export.
 */

%{
#include "extra/ipfilter.h"
%}

// IPFilter is in global namespace (not dcpp::)
enum eDIRECTION { eDIRECTION_IN = 0, eDIRECTION_OUT, eDIRECTION_BOTH };
enum eTableAction { etaDROP = 0, etaACPT };

%nodefaultctor IPFilter;

class IPFilter : public dcpp::ContextAware {
public:
    // ── Static utilities ───────────────────────────────────────
    static uint32_t StringToUint32(const std::string&);
    static std::string Uint32ToString(uint32_t);
    static uint32_t MaskToCIDR(uint32_t);
    static uint32_t MaskForBits(uint32_t);

    // ── Lifecycle ──────────────────────────────────────────────
    void load();
    void shutdown();
    void loadList();
    void saveList();

    // ── Rule management ────────────────────────────────────────
    bool addToRules(const std::string& exp, eDIRECTION direction);
    void remFromRules(std::string exp, eTableAction);
    void changeRuleDirection(std::string exp, eDIRECTION, eTableAction);
    void clearRules();

    void moveRuleUp(uint32_t, eTableAction);
    void moveRuleDown(uint32_t, eTableAction);

    // ── Check ──────────────────────────────────────────────────
    bool OK(const std::string& exp, eDIRECTION direction);

    // ── Import/Export ──────────────────────────────────────────
    void exportTo(std::string path, std::string& error);
    void importFrom(std::string path, std::string& error);
};

%extend IPFilter {
    std::string __str__() {
        return "IPFilter()";
    }
}
