--// vim:ts=4:sw=4:noet
--// auto_greet.lua -- Welcome users who join a hub
--//
--// Usage:
--//   Copy to your scripts directory, or run directly:
--//     eispy lua eval-file examples/lua/auto_greet.lua
--//
--// Chat commands (type in any hub):
--//   /greet on             Enable auto-greeting for this hub
--//   /greet off            Disable auto-greeting for this hub
--//   /greet status         Show current state
--//   /greet msg <text>     Set the greeting message (use %nick% as placeholder)
--//   /greet delay <secs>   Set delay before greeting (default 5s, avoids flood)

if not autogreet then
	autogreet = {}
	autogreet.enabled = {}       -- keyed by hub URL -> bool
	autogreet.message = {}       -- keyed by hub URL -> string
	autogreet.delay   = {}       -- keyed by hub URL -> seconds
	autogreet.pending = {}       -- { time, hub_id, nick } entries
	autogreet.default_msg   = "Welcome, %nick%! Type /help for available commands."
	autogreet.default_delay = 5
end

local function getMsg(url)
	return autogreet.message[url] or autogreet.default_msg
end

local function getDelay(url)
	return autogreet.delay[url] or autogreet.default_delay
end

---------------------------------------------------------------------------
-- Greet via PM after a short delay (avoids flooding on mass-joins)
---------------------------------------------------------------------------

-- Queue a greeting
local function queueGreet(hub, nick)
	local url = hub:getUrl()
	if not autogreet.enabled[url] then return end

	-- Don't greet ourselves
	if nick == hub:getOwnNick() then return end

	table.insert(autogreet.pending, {
		time = os.time() + getDelay(url),
		hub  = hub,
		nick = nick,
	})
end

-- Process the queue on each timer tick
local function processPending()
	local now = os.time()
	local remaining = {}

	for _, entry in ipairs(autogreet.pending) do
		if now >= entry.time then
			-- Make sure the hub is still connected and user is still online
			local hub = entry.hub
			if hub and dcpp:hasHub(hub:getId()) then
				local user = hub:getUser(entry.nick)
				if user then
					local msg = getMsg(hub:getUrl()):gsub("%%nick%%", entry.nick)
					-- Send as a private message, hidden from our own UI (2nd arg = 1)
					user:sendPrivMsgFmt(msg, 1)
				end
			end
		else
			table.insert(remaining, entry)
		end
	end

	autogreet.pending = remaining
end

---------------------------------------------------------------------------
-- Listeners
---------------------------------------------------------------------------

-- NMDC user join
dcpp:setListener("userConnected", "autogreet",
	function(hub, user)
		queueGreet(hub, user:getNick())
	end
)

-- ADC user join
dcpp:setListener("adcUserCon", "autogreet",
	function(hub, user)
		queueGreet(hub, user:getNick())
	end
)

-- Timer — process pending greetings
DC():RunTimer(1)
dcpp:setListener("timer", "autogreet",
	function()
		processPending()
	end
)

---------------------------------------------------------------------------
-- Chat commands
---------------------------------------------------------------------------

dcpp:setListener("ownChatOut", "autogreet",
	function(hub, text)
		local cmd, arg = text:match("^/greet%s+(%S+)%s*(.*)")
		if not cmd then return nil end

		local url = hub:getUrl()
		cmd = cmd:lower()

		if cmd == "on" then
			autogreet.enabled[url] = true
			hub:addLine("*** Auto-greet enabled for this hub")
			return 1
		elseif cmd == "off" then
			autogreet.enabled[url] = false
			hub:addLine("*** Auto-greet disabled for this hub")
			return 1
		elseif cmd == "status" then
			local state = autogreet.enabled[url] and "on" or "off"
			hub:addLine(string.format(
				"*** Auto-greet: %s | delay: %ds | msg: %s",
				state, getDelay(url), getMsg(url)))
			return 1
		elseif cmd == "msg" and arg ~= "" then
			autogreet.message[url] = arg
			hub:addLine("*** Greeting message set to: " .. arg)
			return 1
		elseif cmd == "delay" then
			local secs = tonumber(arg)
			if secs and secs >= 0 then
				autogreet.delay[url] = secs
				hub:addLine("*** Greeting delay set to " .. secs .. "s")
			else
				hub:addLine("*** Usage: /greet delay <seconds>")
			end
			return 1
		end
	end
)

DC():PrintDebug("  ** Loaded auto_greet.lua **")
