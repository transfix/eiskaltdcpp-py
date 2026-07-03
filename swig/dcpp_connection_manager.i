/*
 * dcpp_connection_manager.i — ConnectionManager SWIG wrapping
 *
 * Manages user connections (NMDC & ADC), listening ports, and
 * connection lifecycle (force, disconnect, shutdown).
 */

%{
#include <dcpp/ConnectionManager.h>
using dcpp::ConnectionManager;
%}

%nodefaultctor dcpp::ConnectionManager;

namespace dcpp {

class ConnectionManager : public ContextAware {
public:
    // ── Connection control ──
    void getDownloadConnection(const HintedUser& aUser);
    void force(const UserPtr& aUser);

    void disconnect(const UserPtr& user);
    void disconnect(const UserPtr& user, int isDownload);

    // ── Server socket ──
    void listen();
    void disconnect() noexcept;
    void shutdown();

    // ── Port accessors ──
    const std::string& getPort() const;
    const std::string& getSecurePort() const;
};

}  // namespace dcpp

%extend dcpp::ConnectionManager {
    std::string __str__() {
        return "ConnectionManager(port=" + $self->getPort() +
               ", securePort=" + $self->getSecurePort() + ")";
    }

    %pythoncode %{
    @property
    def port(self):
        """Current listening port."""
        return self.getPort()

    @property
    def secure_port(self):
        """Current secure (TLS) listening port."""
        return self.getSecurePort()
    %}
}
