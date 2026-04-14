/*
 * dcpp_favorite_manager.i — FavoriteManager SWIG wrapping
 *
 * Favorites CRUD: hubs, users, directories, user commands, hub lists.
 */

%{
#include <dcpp/FavoriteManager.h>
#include <dcpp/FavoriteUser.h>
#include <dcpp/FavHubGroup.h>
using dcpp::FavoriteManager;
using dcpp::FavoriteUser;
%}

// FavoriteUser
%nodefaultctor dcpp::FavoriteUser;

namespace dcpp {

class FavoriteUser {
public:
    const UserPtr& getUser() const;
    const std::string& getUrl() const;
    const std::string& getNick() const;
    const std::string& getDescription() const;
    time_t getLastSeen() const;
};

}  // namespace dcpp

%nodefaultctor dcpp::FavoriteManager;

namespace dcpp {

class FavoriteManager : public ContextAware {
public:
    // ── Hub lists ──────────────────────────────────────────────
    StringList getHubLists();
    void setHubList(int aHubList);
    int getSelectedHubList();
    void refresh(bool forceDownload = false);
    bool isDownloading();

    // ── Favorite hubs ──────────────────────────────────────────
    const FavoriteHubEntryList& getFavoriteHubs() const;
    void addFavorite(const FavoriteHubEntry& aEntry);
    void removeFavorite(FavoriteHubEntry* entry);
    bool isFavoriteHub(const std::string& aUrl);
    FavoriteHubEntryPtr getFavoriteHubEntry(const std::string& aServer) const;
    FavoriteHubEntryList getFavoriteHubs(const std::string& group) const;
    bool isPrivate(const std::string& url) const;

    // ── Favorite users ─────────────────────────────────────────
    void addFavoriteUser(const UserPtr& aUser);
    bool isFavoriteUser(const UserPtr& aUser) const;
    void removeFavoriteUser(const UserPtr& aUser);
    bool hasSlot(const UserPtr& aUser) const;
    void setUserDescription(const UserPtr& aUser, const std::string& description);
    void setAutoGrant(const UserPtr& aUser, bool grant);
    time_t getLastSeen(const UserPtr& aUser) const;
    std::string getUserURL(const UserPtr& aUser) const;

    // ── Favorite directories ───────────────────────────────────
    bool addFavoriteDir(const std::string& aDirectory, const std::string& aName);
    bool removeFavoriteDir(const std::string& aName);
    bool renameFavoriteDir(const std::string& aName, const std::string& anotherName);
    StringPairList getFavoriteDirs();

    // ── User commands ──────────────────────────────────────────
    UserCommand addUserCommand(int type, int ctx, int flags,
                               const std::string& name, const std::string& command,
                               const std::string& to, const std::string& hub);
    bool getUserCommand(int cid, UserCommand& uc);
    int findUserCommand(const std::string& aName, const std::string& aUrl);
    bool moveUserCommand(int cid, int pos);
    void updateUserCommand(const UserCommand& uc);
    void removeUserCommand(int cid);
    void removeUserCommand(const std::string& srv);
    void removeHubUserCommands(int ctx, const std::string& hub);

    // ── Persistence ────────────────────────────────────────────
    void load();
    void save();
};

}  // namespace dcpp

%extend dcpp::FavoriteManager {
    std::string __str__() {
        return "FavoriteManager()";
    }
}
