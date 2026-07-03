/*
 * dcpp_types.i — Core dcpp types for SWIG wrapping
 *
 * Wraps: CID, TTHValue (HashValue<TigerHash>), User, UserPtr,
 *        HintedUser, Identity, OnlineUser, FavoriteHubEntry,
 *        HubEntry, UserCommand, StringList, StringPairList, ParamMap
 */

%{
#include <dcpp/CID.h>
#include <dcpp/Encoder.h>
#include <dcpp/HashValue.h>
#include <dcpp/TigerHash.h>
#include <dcpp/MerkleTree.h>
#include <dcpp/Pointer.h>
#include <dcpp/intrusive_ptr.h>
#include <dcpp/User.h>
#include <dcpp/HintedUser.h>
#include <dcpp/OnlineUser.h>
#include <dcpp/HubEntry.h>
#include <dcpp/UserCommand.h>
#include <dcpp/typedefs.h>
#include <dcpp/forward.h>
#include <dcpp/Flags.h>
#include <dcpp/GetSet.h>
#include <dcpp/Util.h>
#include <dcpp/Text.h>

using dcpp::CID;
using dcpp::TigerHash;
using dcpp::HashValue;
using dcpp::TTHValue;
using dcpp::User;
using dcpp::UserPtr;
using dcpp::HintedUser;
using dcpp::Identity;
using dcpp::OnlineUser;
using dcpp::OnlineUserPtr;
using dcpp::HubEntry;
using dcpp::FavoriteHubEntry;
using dcpp::FavoriteHubEntryPtr;
using dcpp::UserCommand;
using dcpp::StringList;
using dcpp::StringPair;
using dcpp::StringPairList;
using dcpp::StringMap;
using dcpp::HintedUserList;
using dcpp::ParamMap;
using dcpp::FavoriteHubEntryList;
%}

// ============================================================================
// Ignore internals that SWIG can't handle or shouldn't expose
// ============================================================================

// Flags base class — ignore template/macro internals
%ignore dcpp::Flags;

// FastAlloc — internal allocator, not needed in Python
%ignore dcpp::FastAlloc;

// intrusive_ptr_base — internal ref counting
%ignore dcpp::intrusive_ptr_base;

// NonCopyable — internal
%ignore dcpp::NonCopyable;

// ============================================================================
// CID — 192-bit client identifier
// ============================================================================

namespace dcpp {

class CID {
public:
    enum { SIZE = 192 / 8 };

    CID();
    explicit CID(const std::string& base32);

    bool operator==(const CID& rhs) const;
    bool operator<(const CID& rhs) const;

    std::string toBase32() const;

    static CID generate();
};

}  // namespace dcpp

%extend dcpp::CID {
    std::string __str__() {
        return $self->toBase32();
    }
    std::string __repr__() {
        return "CID('" + $self->toBase32() + "')";
    }
    size_t __hash__() {
        return $self->toHash();
    }
    bool __eq__(const dcpp::CID& other) {
        return *$self == other;
    }
    bool __ne__(const dcpp::CID& other) {
        return !(*$self == other);
    }
    bool __bool__() {
        return static_cast<bool>(*$self);
    }
}

// ============================================================================
// TTHValue — Tiger Tree Hash (HashValue<TigerHash>)
// ============================================================================

namespace dcpp {

class TigerHash {
public:
    enum { BITS = 192, BYTES = 192 / 8 };
};

template<class Hasher>
struct HashValue {
    HashValue();
    explicit HashValue(const std::string& base32);

    bool operator==(const HashValue& rhs) const;
    bool operator!=(const HashValue& rhs) const;
    bool operator<(const HashValue& rhs) const;

    std::string toBase32() const;
};

}  // namespace dcpp

%template(TTHValue) dcpp::HashValue<dcpp::TigerHash>;

%extend dcpp::HashValue<dcpp::TigerHash> {
    std::string __str__() {
        return $self->toBase32();
    }
    std::string __repr__() {
        return "TTHValue('" + $self->toBase32() + "')";
    }
    size_t __hash__() {
        size_t h;
        memcpy(&h, $self->data, sizeof(size_t));
        return h;
    }
    bool __eq__(const dcpp::HashValue<dcpp::TigerHash>& other) {
        return *$self == other;
    }
    bool __ne__(const dcpp::HashValue<dcpp::TigerHash>& other) {
        return *$self != other;
    }
    bool __bool__() {
        return static_cast<bool>(*$self);
    }
}

// ============================================================================
// intrusive_ptr<User> — UserPtr
// ============================================================================

namespace dcpp {

template<typename T>
class intrusive_ptr {
public:
    T* get() const noexcept;
    explicit operator bool() const noexcept;
};

}  // namespace dcpp

%template(UserPtr) dcpp::intrusive_ptr<dcpp::User>;

%extend dcpp::intrusive_ptr<dcpp::User> {
    bool __bool__() {
        return $self->get() != nullptr;
    }
    bool __eq__(const dcpp::intrusive_ptr<dcpp::User>& other) {
        return $self->get() == other.get();
    }
    bool __ne__(const dcpp::intrusive_ptr<dcpp::User>& other) {
        return $self->get() != other.get();
    }
}

// ============================================================================
// User — connected user
// ============================================================================

%nodefaultctor dcpp::User;

namespace dcpp {

class User {
public:
    enum Bits {
        ONLINE_BIT,
        PASSIVE_BIT,
        NMDC_BIT,
        BOT_BIT,
        TLS_BIT,
        OLD_CLIENT_BIT,
        NO_ADC_1_0_PROTOCOL_BIT,
        NO_ADCS_0_10_PROTOCOL_BIT,
        NAT_TRAVERSAL_BIT
    };

    enum UserFlags {
        ONLINE      = 1 << 0,
        PASSIVE     = 1 << 1,
        NMDC        = 1 << 2,
        BOT         = 1 << 3,
        TLS         = 1 << 4,
        OLD_CLIENT  = 1 << 5,
        NO_ADC_1_0_PROTOCOL   = 1 << 6,
        NO_ADCS_0_10_PROTOCOL = 1 << 7,
        NAT_TRAVERSAL = 1 << 9
    };

    const dcpp::CID& getCID() const;
    bool isOnline() const;
    bool isNMDC() const;
};

}  // namespace dcpp

%extend dcpp::User {
    std::string __str__() {
        return "User(cid='" + $self->getCID().toBase32() +
               "', online=" + ($self->isOnline() ? "True" : "False") + ")";
    }
    std::string __repr__() {
        return "User('" + $self->getCID().toBase32() + "')";
    }
}

// ============================================================================
// HintedUser — User + hub URL hint
// ============================================================================

namespace dcpp {

struct HintedUser {
    dcpp::intrusive_ptr<dcpp::User> user;
    std::string hint;

    HintedUser();
    HintedUser(const dcpp::intrusive_ptr<dcpp::User>& user, const std::string& hint);

    bool operator==(const dcpp::intrusive_ptr<dcpp::User>& rhs) const;
    bool operator==(const HintedUser& rhs) const;

    explicit operator bool() const;
};

}  // namespace dcpp

%extend dcpp::HintedUser {
    std::string __str__() {
        std::string cid_str = $self->user ? $self->user->getCID().toBase32() : "null";
        return "HintedUser(cid='" + cid_str + "', hint='" + $self->hint + "')";
    }
    std::string __repr__() {
        std::string cid_str = $self->user ? $self->user->getCID().toBase32() : "null";
        return "HintedUser('" + cid_str + "', '" + $self->hint + "')";
    }
    bool __bool__() {
        return static_cast<bool>(*$self);
    }
}

// ============================================================================
// Identity — user identity fields within a hub
// ============================================================================

namespace dcpp {

class Identity {
public:
    enum ClientType {
        CT_BOT = 1,
        CT_REGGED = 2,
        CT_OP = 4,
        CT_SU = 8,
        CT_OWNER = 16,
        CT_HUB = 32,
        CT_HIDDEN = 64
    };

    enum StatusFlags {
        NORMAL = 0x01,
        AWAY   = 0x02,
        TLS    = 0x10,
        NAT    = 0x20
    };

    Identity();

    std::string getNick() const;
    std::string getDescription() const;
    std::string getIp() const;
    std::string getUdpPort() const;
    std::string getEmail() const;
    std::string getConnection() const;

    void setNick(const std::string& v);
    void setDescription(const std::string& v);
    void setIp(const std::string& v);
    void setEmail(const std::string& v);

    int64_t getBytesShared() const;

    bool isOp() const;
    bool isBot() const;
    bool isHub() const;
    bool isHidden() const;
    bool isRegistered() const;
    bool isAway() const;

    std::string getTag() const;
    std::string getApplication() const;
    bool supports(const std::string& name) const;

    std::string get(const char* name) const;
    void set(const char* name, const std::string& val);
    bool isSet(const char* name) const;

    const dcpp::intrusive_ptr<dcpp::User>& getUser() const;
    uint32_t getSID() const;

    bool isSelf() const;
};

}  // namespace dcpp

%extend dcpp::Identity {
    std::string __str__() {
        return "Identity(nick='" + $self->getNick() +
               "', shared=" + std::to_string($self->getBytesShared()) +
               ", op=" + ($self->isOp() ? "True" : "False") + ")";
    }
    std::string __repr__() {
        return "Identity('" + $self->getNick() + "')";
    }
}

// ============================================================================
// HubEntry — public hub listing entry
// ============================================================================

namespace dcpp {

class HubEntry {
public:
    HubEntry();

    const std::string& getName() const;
    void setName(const std::string&);
    const std::string& getServer() const;
    void setServer(const std::string&);
    const std::string& getDescription() const;
    void setDescription(const std::string&);
    const std::string& getCountry() const;
    const std::string& getRating() const;
    float getReliability() const;
    int64_t getShared() const;
    int64_t getMinShare() const;
    int getUsers() const;
    int getMinSlots() const;
    int getMaxHubs() const;
    int getMaxUsers() const;
};

}  // namespace dcpp

%extend dcpp::HubEntry {
    std::string __str__() {
        return "HubEntry(name='" + $self->getName() +
               "', server='" + $self->getServer() +
               "', users=" + std::to_string($self->getUsers()) + ")";
    }
}

// ============================================================================
// FavoriteHubEntry — saved hub bookmark
// ============================================================================

// FavoriteHubEntry takes DCContext& in constructor — ignore that for SWIG
// since Python shouldn't construct these directly
%ignore dcpp::FavoriteHubEntry::FavoriteHubEntry;
%ignore dcpp::FavoriteHubEntry::ctx;

namespace dcpp {

class FavoriteHubEntry {
public:
    const std::string& getNick(bool useDefault = true) const;
    void setNick(const std::string& aNick);

    const std::string& getUserDescription() const;
    void setUserDescription(const std::string&);
    const std::string& getName() const;
    void setName(const std::string&);
    const std::string& getServer() const;
    void setServer(const std::string&);
    const std::string& getHubDescription() const;
    void setHubDescription(const std::string&);
    const std::string& getPassword() const;
    void setPassword(const std::string&);
    const std::string& getEncoding() const;
    void setEncoding(const std::string&);
    bool getConnect() const;
    void setConnect(bool);
    int getMode() const;
    void setMode(int);
    const std::string& getGroup() const;
    void setGroup(const std::string&);
    uint32_t getSearchInterval() const;
    void setSearchInterval(uint32_t);
};

}  // namespace dcpp

%extend dcpp::FavoriteHubEntry {
    std::string __str__() {
        return "FavoriteHubEntry(name='" + $self->getName() +
               "', server='" + $self->getServer() + "')";
    }
    std::string __repr__() {
        return "FavoriteHubEntry('" + $self->getServer() + "')";
    }
}

// ============================================================================
// UserCommand — user-defined hub command
// ============================================================================

namespace dcpp {

class UserCommand {
public:
    typedef std::vector<UserCommand> List;

    enum {
        TYPE_SEPARATOR,
        TYPE_RAW,
        TYPE_RAW_ONCE,
        TYPE_REMOVE,
        TYPE_CHAT,
        TYPE_CHAT_ONCE,
        TYPE_CLEAR = 255
    };

    enum {
        CONTEXT_HUB = 0x01,
        CONTEXT_USER = 0x02,
        CONTEXT_SEARCH = 0x04,
        CONTEXT_FILELIST = 0x08,
        CONTEXT_MASK = 0x0F
    };

    UserCommand();

    bool isRaw() const;
    bool isChat() const;
    bool once() const;

    int getId() const;
    int getType() const;
    int getCtx() const;
    const std::string& getName() const;
    const std::string& getCommand() const;
    const std::string& getTo() const;
    const std::string& getHub() const;

    void setId(int);
    void setType(int);
    void setCtx(int);
    void setName(const std::string&);
    void setCommand(const std::string&);
    void setTo(const std::string&);
    void setHub(const std::string&);
};

}  // namespace dcpp

%extend dcpp::UserCommand {
    std::string __str__() {
        return "UserCommand(id=" + std::to_string($self->getId()) +
               ", name='" + $self->getName() +
               "', type=" + std::to_string($self->getType()) + ")";
    }
}

// ============================================================================
// STL container templates used across managers
// ============================================================================

namespace std {
    // Note: StringVector (vector<string>) already defined in dc_core.i
    %template(DcppStringPairList) vector<std::pair<std::string, std::string>>;
}

// StringPair
namespace dcpp {
    typedef std::pair<std::string, std::string> StringPair;
    typedef std::vector<std::string> StringList;
    typedef std::vector<StringPair> StringPairList;
    typedef std::unordered_map<std::string, std::string> StringMap;

    typedef dcpp::intrusive_ptr<dcpp::User> UserPtr;
    typedef dcpp::FavoriteHubEntry* FavoriteHubEntryPtr;
    typedef std::vector<FavoriteHubEntryPtr> FavoriteHubEntryList;
    typedef std::vector<dcpp::HintedUser> HintedUserList;
    typedef std::vector<dcpp::HubEntry> HubEntryList;
    typedef dcpp::StringMap ParamMap;
}

namespace std {
    %template(FavoriteHubEntryPtrList) vector<dcpp::FavoriteHubEntry*>;
    %template(HintedUserList) vector<dcpp::HintedUser>;
    %template(HubEntryList) vector<dcpp::HubEntry>;
    %template(UserCommandList) vector<dcpp::UserCommand>;
}
