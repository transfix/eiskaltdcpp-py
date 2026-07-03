/*
 * dcpp_crypto_manager.i — CryptoManager SWIG wrapping
 *
 * TLS/certificate management: load/generate certs, check status.
 */

%{
#include <dcpp/CryptoManager.h>
using dcpp::CryptoManager;
%}

%nodefaultctor dcpp::CryptoManager;

namespace dcpp {

class CryptoManager : public ContextAware {
public:
    // ── Key/Lock (NMDC protocol) ───────────────────────────────
    std::string makeKey(const std::string& aLock);
    const std::string& getLock();
    const std::string& getPk();
    bool isExtended(const std::string& aLock);

    // ── TLS ────────────────────────────────────────────────────
    void loadCertificates() noexcept;
    void generateCertificate();
    bool checkCertificate() noexcept;
    bool TLSOk() const noexcept;
};

}  // namespace dcpp

%extend dcpp::CryptoManager {
    std::string __str__() {
        return "CryptoManager(tls_ok=" +
               std::string($self->TLSOk() ? "True" : "False") + ")";
    }

    %pythoncode %{
    @property
    def tls_ok(self):
        """Whether TLS is properly configured."""
        return self.TLSOk()
    %}
}
