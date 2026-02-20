--// vim:ts=4:sw=4:noet
--// hub_monitor.lua -- Track hub events, user counts, and connection stats
--//
--// Usage:
--//   Copy to your scripts directory, or run directly:
--//     eispy lua eval-file examples/lua/hub_monitor.lua
--//
--// Chat commands (type in any hub):
--//   /mon status      Show monitoring stats for the current hub
--//   /mon all         Show stats for all connected hubs
--//   /mon peak        Show peak user count
--//   /mon reset       Reset stats for the current hub

if not hubmon then
	hubmon = {}
	hubmon.stats = {}  -- keyed by hub URL
end

local function initStats(url)
	if not hubmon.stats[url] then
		hubmon.stats[url] = {
			users_joined    = 0,
			users_left      = 0,
			connects        = 0,
			disconnects     = 0,
			peak_users      = 0,
			current_users   = 0,
			last_connect    = nil,
			last_disconnect = nil,
			start_time      = os.time(),
		}
	end
	return hubmon.stats[url]
end

local function formatUptime(seconds)
	local d = math.floor(seconds / 86400)
	local h = math.floor((seconds % 86400) / 3600)
	local m = math.floor((seconds % 3600) / 60)
	local s = seconds % 60
	if d > 0 then
		return string.format("%dd %02d:%02d:%02d", d, h, m, s)
	else
		return string.format("%02d:%02d:%02d", h, m, s)
	end
end

---------------------------------------------------------------------------
-- Listeners
---------------------------------------------------------------------------

-- Hub connected
dcpp:setListener("connected", "hubmon",
	function(hub)
		local st = initStats(hub:getUrl())
		st.connects = st.connects + 1
		st.last_connect = os.time()
		st.current_users = 0
		DC():PrintDebug("[hubmon] Connected to " .. hub:getUrl())
	end
)

-- Hub disconnected
dcpp:setListener("disconnected", "hubmon",
	function(hub)
		local st = hubmon.stats[hub:getUrl()]
		if st then
			st.disconnects = st.disconnects + 1
			st.last_disconnect = os.time()
			DC():PrintDebug(string.format(
				"[hubmon] Disconnected from %s (was online %s)",
				hub:getUrl(),
				st.last_connect
					and formatUptime(os.time() - st.last_connect)
					or "?"))
		end
	end
)

-- NMDC user join
dcpp:setListener("userConnected", "hubmon",
	function(hub, user)
		local st = initStats(hub:getUrl())
		st.users_joined  = st.users_joined + 1
		st.current_users = st.current_users + 1
		if st.current_users > st.peak_users then
			st.peak_users = st.current_users
		end
	end
)

-- ADC user join
dcpp:setListener("adcUserCon", "hubmon",
	function(hub, user)
		local st = initStats(hub:getUrl())
		st.users_joined  = st.users_joined + 1
		st.current_users = st.current_users + 1
		if st.current_users > st.peak_users then
			st.peak_users = st.current_users
		end
	end
)

-- NMDC user leave
dcpp:setListener("userQuit", "hubmon",
	function(hub, nick)
		local st = hubmon.stats[hub:getUrl()]
		if st then
			st.users_left    = st.users_left + 1
			st.current_users = math.max(0, st.current_users - 1)
		end
	end
)

-- ADC user leave
dcpp:setListener("adcUserQui", "hubmon",
	function(hub, sid, flags)
		local st = hubmon.stats[hub:getUrl()]
		if st then
			st.users_left    = st.users_left + 1
			st.current_users = math.max(0, st.current_users - 1)
		end
	end
)

---------------------------------------------------------------------------
-- Display helpers
---------------------------------------------------------------------------

local function showStats(hub, url)
	local st = hubmon.stats[url]
	if not st then
		hub:addLine("*** No stats for " .. url)
		return
	end

	local uptime = formatUptime(os.time() - st.start_time)
	hub:addLine(string.format(
		"*** [%s]\n" ..
		"    Monitoring for: %s\n" ..
		"    Connections: %d connect(s), %d disconnect(s)\n" ..
		"    Users now: %d | Peak: %d\n" ..
		"    Joins: %d | Parts: %d",
		url, uptime,
		st.connects, st.disconnects,
		st.current_users, st.peak_users,
		st.users_joined, st.users_left))
end

---------------------------------------------------------------------------
-- Chat commands
---------------------------------------------------------------------------

dcpp:setListener("ownChatOut", "hubmon",
	function(hub, text)
		local cmd = text:match("^/mon%s+(%S+)")
		if not cmd then return nil end

		cmd = cmd:lower()

		if cmd == "status" then
			showStats(hub, hub:getUrl())
			return 1
		elseif cmd == "all" then
			local count = 0
			for url, _ in pairs(hubmon.stats) do
				showStats(hub, url)
				count = count + 1
			end
			if count == 0 then
				hub:addLine("*** No hub stats recorded yet")
			end
			return 1
		elseif cmd == "peak" then
			local st = hubmon.stats[hub:getUrl()]
			if st then
				hub:addLine("*** Peak users: " .. st.peak_users)
			else
				hub:addLine("*** No stats for this hub")
			end
			return 1
		elseif cmd == "reset" then
			hubmon.stats[hub:getUrl()] = nil
			initStats(hub:getUrl())
			hub:addLine("*** Stats reset for this hub")
			return 1
		end
	end
)

DC():PrintDebug("  ** Loaded hub_monitor.lua **")
