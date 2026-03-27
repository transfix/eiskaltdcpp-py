/*
 * dcpp_settings.i — SettingsManager SWIG wrapping
 *
 * Wraps all setting enums (StrSetting, IntSetting, Int64Setting, FloatSetting)
 * and the get/set/getDefault/setDefault/load/save methods.
 * Also wraps search type management.
 */

%{
#include <dcpp/SettingsManager.h>
using dcpp::SettingsManager;
%}

%nodefaultctor dcpp::SettingsManager;

namespace dcpp {

class SettingsManager : public ContextAware {
public:
    // ── Setting type enums ─────────────────────────────────────
    enum Types {
        TYPE_STRING,
        TYPE_INT,
        TYPE_INT64
    };

    enum StrSetting { STR_FIRST,
        NICK = STR_FIRST, UPLOAD_SPEED, DESCRIPTION, DOWNLOAD_DIRECTORY,
        EMAIL, EXTERNAL_IP, HUBLIST_SERVERS,
        HTTP_PROXY, LOG_DIRECTORY, LOG_FORMAT_POST_DOWNLOAD, LOG_FORMAT_POST_FINISHED_DOWNLOAD,
        LOG_FORMAT_POST_UPLOAD, LOG_FORMAT_MAIN_CHAT,
        LOG_FORMAT_PRIVATE_CHAT, TEMP_DOWNLOAD_DIRECTORY,
        BIND_ADDRESS, SOCKS_SERVER, SOCKS_USER, SOCKS_PASSWORD,
        CONFIG_VERSION, DEFAULT_AWAY_MESSAGE, TIME_STAMPS_FORMAT,
        PRIVATE_ID, LOG_FILE_MAIN_CHAT, LOG_FILE_PRIVATE_CHAT,
        LOG_FILE_STATUS, LOG_FILE_UPLOAD,
        LOG_FILE_DOWNLOAD, LOG_FILE_FINISHED_DOWNLOAD, LOG_FILE_SYSTEM, LOG_FORMAT_SYSTEM,
        LOG_FORMAT_STATUS, LOG_FILE_SPY, LOG_FORMAT_SPY, TLS_PRIVATE_KEY_FILE,
        TLS_CERTIFICATE_FILE, TLS_TRUSTED_CERTIFICATES_PATH,
        LANGUAGE, SKIPLIST_SHARE, INTERNETIP, BIND_IFACE_NAME,
        DHT_KEY, DYNDNS_SERVER, MIME_HANDLER,
        LOG_FILE_CMD_DEBUG, LOG_FORMAT_CMD_DEBUG,
        STR_LAST
    };

    enum IntSetting { INT_FIRST = STR_LAST + 1,
        INCOMING_CONNECTIONS = INT_FIRST, TCP_PORT, SLOTS,
        AUTO_FOLLOW, SHARE_HIDDEN, FILTER_MESSAGES,
        AUTO_SEARCH, AUTO_SEARCH_TIME,
        REPORT_ALTERNATES, TIME_STAMPS,
        IGNORE_HUB_PMS, IGNORE_BOT_PMS, LIST_DUPES, BUFFER_SIZE,
        DOWNLOAD_SLOTS, MAX_DOWNLOAD_SPEED, LOG_MAIN_CHAT,
        LOG_PRIVATE_CHAT, LOG_DOWNLOADS, LOG_FINISHED_DOWNLOADS,
        LOG_UPLOADS, MIN_UPLOAD_SPEED,
        AUTO_AWAY, SOCKS_PORT, SOCKS_RESOLVE,
        KEEP_LISTS, AUTO_KICK, COMPRESS_TRANSFERS,
        SFV_CHECK, MAX_COMPRESSION, NO_AWAYMSG_TO_BOTS, SKIP_ZERO_BYTE,
        ADLS_BREAK_ON_FIRST, HUB_USER_COMMANDS, AUTO_SEARCH_AUTO_MATCH,
        LOG_SYSTEM,
        LOG_FILELIST_TRANSFERS, SEND_UNKNOWN_COMMANDS, MAX_HASH_SPEED,
        GET_USER_COUNTRY, LOG_STATUS_MESSAGES, SEARCH_PASSIVE,
        ADD_FINISHED_INSTANTLY, DONT_DL_ALREADY_SHARED, UDP_PORT,
        SHOW_LAST_LINES_LOG, ADC_DEBUG,
        SEARCH_HISTORY, SET_MINISLOT_SIZE, MAX_FILELIST_SIZE,
        PRIO_HIGHEST_SIZE, PRIO_HIGH_SIZE, PRIO_NORMAL_SIZE,
        PRIO_LOW_SIZE, PRIO_LOWEST, AUTODROP_SPEED, AUTODROP_INTERVAL,
        AUTODROP_ELAPSED, AUTODROP_INACTIVITY, AUTODROP_MINSOURCES,
        AUTODROP_FILESIZE, AUTODROP_ALL, AUTODROP_FILELISTS,
        AUTODROP_DISCONNECT, OUTGOING_CONNECTIONS, NO_IP_OVERRIDE,
        NO_USE_TEMP_DIR, SHARE_TEMP_FILES, SEARCH_ONLY_FREE_SLOTS,
        LAST_SEARCH_TYPE,
        SOCKET_IN_BUFFER, SOCKET_OUT_BUFFER,
        AUTO_REFRESH_TIME, HASHING_START_DELAY, USE_TLS, AUTO_SEARCH_LIMIT,
        AUTO_KICK_NO_FAVS, PROMPT_PASSWORD,
        DONT_DL_ALREADY_QUEUED,
        MAX_COMMAND_LENGTH, ALLOW_UNTRUSTED_HUBS, ALLOW_UNTRUSTED_CLIENTS,
        TLS_PORT, FAST_HASH, SEGMENTED_DL,
        FOLLOW_LINKS, SEND_BLOOM,
        SEARCH_FILTER_SHARED, FINISHED_DL_ONLY_FULL,
        SEARCH_MERGE, HASH_BUFFER_SIZE_MB, HASH_BUFFER_POPULATE,
        HASH_BUFFER_NORESERVE, HASH_BUFFER_PRIVATE,
        USE_DHT, DHT_PORT,
        RECONNECT_DELAY, AUTO_DETECT_CONNECTION, BANDWIDTH_LIMIT_START,
        BANDWIDTH_LIMIT_END, THROTTLE_ENABLE, TIME_DEPENDENT_THROTTLE,
        MAX_DOWNLOAD_SPEED_ALTERNATE, MAX_UPLOAD_SPEED_ALTERNATE,
        MAX_DOWNLOAD_SPEED_MAIN, MAX_UPLOAD_SPEED_MAIN,
        SLOTS_ALTERNATE_LIMITING, SLOTS_PRIMARY, KEEP_FINISHED_FILES,
        SHOW_FREE_SLOTS_DESC, USE_IP, OVERLAP_CHUNKS, CASESENSITIVE_FILELIST,
        IPFILTER, TEXT_COLOR, USE_LUA, ALLOW_NATT, IP_TOS_VALUE, SEGMENT_SIZE,
        BIND_IFACE, MINIMUM_SEARCH_INTERVAL, DYNDNS_ENABLE, ALLOW_UPLOAD_MULTI_HUB,
        USE_ADL_ONLY_OWN_LIST, ALLOW_SIM_UPLOADS, CHECK_TARGETS_PATHS_ON_START,
        NMDC_DEBUG, SHARE_SKIP_ZERO_BYTE, REQUIRE_TLS, LOG_SPY,
        APP_UNIT_BASE,
        LOG_CMD_DEBUG,
        INT_LAST
    };

    enum Int64Setting { INT64_FIRST = INT_LAST + 1,
        TOTAL_UPLOAD = INT64_FIRST, TOTAL_DOWNLOAD,
        INT64_LAST
    };

    enum FloatSetting { FLOAT_FIRST = INT64_LAST + 1,
        FLOAT_LAST = FLOAT_FIRST, SETTINGS_LAST = FLOAT_LAST
    };

    // Connection type enums
    enum { INCOMING_DIRECT, INCOMING_FIREWALL_UPNP, INCOMING_FIREWALL_NAT, INCOMING_FIREWALL_PASSIVE };
    enum { OUTGOING_DIRECT, OUTGOING_SOCKS5 };

    // ── Getters ────────────────────────────────────────────────
    const std::string& get(StrSetting key, bool useDefault = true) const;
    int get(IntSetting key, bool useDefault = true) const;
    bool getBool(IntSetting key, bool useDefault = true) const;
    int64_t get(Int64Setting key, bool useDefault = true) const;
    float get(FloatSetting key, bool useDefault = true) const;

    // ── Setters ────────────────────────────────────────────────
    void set(StrSetting key, std::string const& value);
    void set(IntSetting key, int value);
    void set(IntSetting key, bool value);
    void set(Int64Setting key, int64_t value);
    void set(FloatSetting key, float value);

    // ── Defaults ───────────────────────────────────────────────
    const std::string& getDefault(StrSetting key) const;
    int getDefault(IntSetting key) const;
    int64_t getDefault(Int64Setting key) const;
    float getDefault(FloatSetting key) const;

    void setDefault(StrSetting key, std::string const& value);
    void setDefault(IntSetting key, int value);
    void setDefault(Int64Setting key, int64_t value);
    void setDefault(FloatSetting key, float value);

    bool isDefault(size_t key);
    void unset(size_t key);

    // ── Persistence ────────────────────────────────────────────
    void load();
    void save();
    void load(const std::string& aFileName);
    void save(const std::string& aFileName);

    // ── Search types ───────────────────────────────────────────
    void setSearchTypeDefaults();
    void addSearchType(const std::string& name, const StringList& extensions, bool validated = false);
    void delSearchType(const std::string& name);
    void renameSearchType(const std::string& oldName, const std::string& newName);
    void modSearchType(const std::string& name, const StringList& extensions);
    const StringList& getExtensions(const std::string& name);
};

}  // namespace dcpp

%extend dcpp::SettingsManager {
    std::string __str__() {
        return "SettingsManager()";
    }

    %pythoncode %{
    @property
    def nick(self):
        """Get the configured nick."""
        return self.get(SettingsManager.NICK)

    @nick.setter
    def nick(self, value):
        self.set(SettingsManager.NICK, value)

    @property
    def download_directory(self):
        """Get the configured download directory."""
        return self.get(SettingsManager.DOWNLOAD_DIRECTORY)

    @download_directory.setter
    def download_directory(self, value):
        self.set(SettingsManager.DOWNLOAD_DIRECTORY, value)

    @property
    def slots(self):
        """Get the number of upload slots."""
        return self.get(SettingsManager.SLOTS)

    @slots.setter
    def slots(self, value):
        self.set(SettingsManager.SLOTS, value)

    @property
    def tcp_port(self):
        return self.get(SettingsManager.TCP_PORT)

    @tcp_port.setter
    def tcp_port(self, value):
        self.set(SettingsManager.TCP_PORT, value)
    %}
}
