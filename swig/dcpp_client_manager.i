/*
 * dcpp_client_manager.i — ClientManager SWIG wrapping
 *
 * Hub/user management: connect/disconnect hubs, find users, get nicks,
 * send private messages, search, etc.
 */

%{
#include <dcpp/ClientManager.h>
#include <dcpp/Client.h>
using dcpp::ClientManager;
using dcpp::Client;
%}

// Don't expose Client internals — just enough for getClient/putClient
%ignore dcpp::Client::connect;
%ignore dcpp::Client::disconnect;

%nodefaultctor dcpp::ClientManager;

namespace dcpp {

// Forward declare so SWIG knows about Client* return type
class Client;

class ClientManager : public ContextAware {
public:
    // ── Hub management ─────────────────────────────────────────
    Client* getClient(const std::string& aHubURL);
    void putClient(Client* aClient);

    // ── User counts ────────────────────────────────────────────
    size_t getUserCount() const;
    int64_t getAvailable() const;

    // ── Nick/hub resolution ────────────────────────────────────
    StringList getNicks(const CID& cid, const std::string& hintUrl);
    StringList getHubs(const CID& cid, const std::string& hintUrl);
    StringList getHubNames(const CID& cid, const std::string& hintUrl);
    StringList getHubUrls(const CID& cid) const;

    StringList getNicks(const CID& cid, const std::string& hintUrl, bool priv);
    StringList getHubs(const CID& cid, const std::string& hintUrl, bool priv);
    StringList getHubNames(const CID& cid, const std::string& hintUrl, bool priv);

    StringList getNicks(const HintedUser& user);
    StringList getHubNames(const HintedUser& user);
    StringList getHubs(const HintedUser& user);

    // ── User info ──────────────────────────────────────────────
    std::string getField(const CID& cid, const std::string& hintUrl, const char* field) const;
    std::string getConnection(const CID& cid) const;
    uint8_t getSlots(const CID& cid) const;

    // ── Connection status ──────────────────────────────────────
    bool isConnected(const std::string& aUrl) const;

    // ── Search ─────────────────────────────────────────────────
    void search(int aSizeMode, int64_t aSize, int aFileType,
                const std::string& aString, const std::string& aToken,
                void* aOwner = 0);

    void cancelSearch(void* aOwner);

    // ── Hub info ───────────────────────────────────────────────
    void infoUpdated();

    // ── User lookup ────────────────────────────────────────────
    UserPtr getUser(const std::string& aNick, const std::string& aHubUrl) noexcept;
    UserPtr getUser(const CID& cid) noexcept;

    std::string findHub(const std::string& ipPort) const;
    std::string findHubEncoding(const std::string& aUrl) const;

    UserPtr findUser(const std::string& aNick, const std::string& aHubUrl) const noexcept;
    UserPtr findUser(const CID& cid) const noexcept;
    UserPtr findLegacyUser(const std::string& aNick) const noexcept;

    bool isOnline(const UserPtr& aUser) const;

    Identity getOnlineUserIdentity(const UserPtr& aUser) const;

    int64_t getBytesShared(const UserPtr& p) const;

    bool isOp(const UserPtr& aUser, const std::string& aHubUrl) const;

    CID makeCid(const std::string& nick, const std::string& hubUrl) const noexcept;

    UserPtr& getMe();

    // ── Messaging ──────────────────────────────────────────────
    void privateMessage(const HintedUser& user, const std::string& msg, bool thirdPerson);

    // ── Connection mode ────────────────────────────────────────
    int getMode(const std::string& aHubUrl) const;
    bool isActive(const std::string& aHubUrl = "") const;

    // ── Persistence ────────────────────────────────────────────
    void loadUsers();
    void saveUsers() const;
    void saveUser(const CID& cid);

    CID getMyCID();
    const CID& getMyPID();
};

}  // namespace dcpp

%extend dcpp::ClientManager {
    std::string __str__() {
        return "ClientManager(users=" + std::to_string($self->getUserCount()) + ")";
    }
}
