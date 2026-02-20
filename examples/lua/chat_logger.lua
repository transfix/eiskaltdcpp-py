--// vim:ts=4:sw=4:noet
--// chat_logger.lua -- Log all hub chat to timestamped daily files
--//
--// Usage:
--//   Copy to your scripts directory, or run directly:
--//     eispy lua eval-file examples/lua/chat_logger.lua
--//
--// Logs are written to <config_dir>/logs/<hub_address>/<date>.log
--// Each line is timestamped: [HH:MM:SS] <Nick> message
--//
--// Chat commands (type in any hub):
--//   /log on       Enable logging for the current hub
--//   /log off      Disable logging for the current hub
--//   /log status   Show whether logging is on or off
--//   /log path     Show the current log file path

if not chatlog then
	chatlog = {}
	chatlog.enabled = {}  -- keyed by hub URL
end

-- Ensure the log directory exists (best-effort with os.execute)
local function ensureDir(path)
	os.execute('mkdir -p "' .. path .. '"')
end

-- Sanitise hub address for use as a directory name
local function sanitiseAddress(addr)
	return addr:gsub("[:/\\%?%*\"|<>]", "_")
end

-- Get the log file path for a hub on a given date
local function logPath(hub)
	local base = DC():GetConfigPath() .. "logs/"
	local dir  = base .. sanitiseAddress(hub:getAddress()) .. "/"
	local file = os.date("%Y-%m-%d") .. ".log"
	return dir, dir .. file
end

-- Append a line to the log file
local function writeLine(hub, line)
	local url = hub:getUrl()
	if not chatlog.enabled[url] then return end

	local dir, path = logPath(hub)
	ensureDir(dir)

	local f = io.open(path, "a")
	if f then
		f:write(line .. "\n")
		f:close()
	end
end

-- Format a timestamped chat line
local function fmtChat(nick, text)
	return os.date("[%H:%M:%S]") .. " <" .. nick .. "> " .. text
end

local function fmtSystem(text)
	return os.date("[%H:%M:%S]") .. " *** " .. text
end

---------------------------------------------------------------------------
-- Listeners
---------------------------------------------------------------------------

-- NMDC public chat
dcpp:setListener("chat", "chatlog",
	function(hub, user, text)
		writeLine(hub, fmtChat(user:getNick(), text))
	end
)

-- ADC public chat
dcpp:setListener("adcChat", "chatlog",
	function(hub, user, text, me_msg)
		if me_msg then
			writeLine(hub, fmtChat(user:getNick(), "* " .. text))
		else
			writeLine(hub, fmtChat(user:getNick(), text))
		end
	end
)

-- NMDC private messages
dcpp:setListener("pm", "chatlog",
	function(hub, user, text)
		writeLine(hub, os.date("[%H:%M:%S]") .. " [PM] <" .. user:getNick() .. "> " .. text)
	end
)

-- ADC private messages
dcpp:setListener("adcPm", "chatlog",
	function(hub, user, text)
		writeLine(hub, os.date("[%H:%M:%S]") .. " [PM] <" .. user:getNick() .. "> " .. text)
	end
)

-- Log connect / disconnect
dcpp:setListener("connected", "chatlog",
	function(hub)
		-- Auto-enable logging for every hub by default
		local url = hub:getUrl()
		if chatlog.enabled[url] == nil then
			chatlog.enabled[url] = true
		end
		writeLine(hub, fmtSystem("Connected to " .. hub:getUrl()))
	end
)

dcpp:setListener("disconnected", "chatlog",
	function(hub)
		writeLine(hub, fmtSystem("Disconnected from " .. hub:getUrl()))
	end
)

-- User join/part
dcpp:setListener("userConnected", "chatlog",
	function(hub, user)
		writeLine(hub, fmtSystem(user:getNick() .. " joined"))
	end
)

dcpp:setListener("userQuit", "chatlog",
	function(hub, nick)
		writeLine(hub, fmtSystem(nick .. " left"))
	end
)

---------------------------------------------------------------------------
-- Chat commands
---------------------------------------------------------------------------

dcpp:setListener("ownChatOut", "chatlog",
	function(hub, text)
		local cmd = text:match("^/log%s+(%S+)")
		if not cmd then return nil end

		local url = hub:getUrl()
		if cmd == "on" then
			chatlog.enabled[url] = true
			hub:addLine("*** Chat logging enabled")
			return 1
		elseif cmd == "off" then
			chatlog.enabled[url] = false
			hub:addLine("*** Chat logging disabled")
			return 1
		elseif cmd == "status" then
			local state = chatlog.enabled[url] and "on" or "off"
			hub:addLine("*** Chat logging is " .. state)
			return 1
		elseif cmd == "path" then
			local _, path = logPath(hub)
			hub:addLine("*** Log file: " .. path)
			return 1
		end
	end
)

DC():PrintDebug("  ** Loaded chat_logger.lua **")
