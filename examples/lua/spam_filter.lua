--// vim:ts=4:sw=4:noet
--// spam_filter.lua -- Block messages matching configurable keyword patterns
--//
--// Usage:
--//   Copy to your scripts directory, or run directly:
--//     eispy lua eval-file examples/lua/spam_filter.lua
--//
--// Chat commands (type in any hub):
--//   /spam add <pattern>    Add a Lua pattern to the block list
--//   /spam del <pattern>    Remove a pattern from the block list
--//   /spam list             Show all patterns
--//   /spam clear            Remove all patterns
--//   /spam stats            Show how many messages were blocked
--//   /spam on               Enable the filter (default)
--//   /spam off              Disable the filter
--//
--// Patterns use Lua's string.find syntax.  Simple substrings work
--// ("buy cheap") as well as Lua patterns ("https?://bit%.ly").

if not spamfilter then
	spamfilter = {}
	spamfilter.enabled  = true
	spamfilter.blocked  = 0
	spamfilter.patterns = {}
	-- Some sensible defaults
	spamfilter.patterns = {
		"https?://bit%.ly",
		"https?://tinyurl%.com",
		"free%s+download",
		"earn%s+money",
	}
end

-- Persist patterns to config
local function patternsFile()
	return DC():GetConfigScriptsPath() .. "spam_patterns.txt"
end

local function savePatterns()
	local f = io.open(patternsFile(), "w")
	if f then
		for _, p in ipairs(spamfilter.patterns) do
			f:write(p .. "\n")
		end
		f:close()
	end
end

local function loadPatterns()
	local f = io.open(patternsFile(), "r")
	if f then
		spamfilter.patterns = {}
		for line in f:lines() do
			line = line:match("^%s*(.-)%s*$")  -- trim
			if line ~= "" then
				table.insert(spamfilter.patterns, line)
			end
		end
		f:close()
	end
end

loadPatterns()

-- Check a message against all patterns
local function isSpam(text)
	local lower = text:lower()
	for _, pattern in ipairs(spamfilter.patterns) do
		if lower:find(pattern:lower()) then
			return true, pattern
		end
	end
	return false
end

---------------------------------------------------------------------------
-- Listeners — filter incoming chat and PMs
---------------------------------------------------------------------------

local function filterChat(hub, user, text)
	if not spamfilter.enabled then return nil end

	local blocked, pattern = isSpam(text)
	if blocked then
		spamfilter.blocked = spamfilter.blocked + 1
		DC():PrintDebug(string.format(
			"[spam] Blocked message from %s (pattern: %s): %s",
			user:getNick(), pattern, text:sub(1, 80)))
		return 1  -- suppress the message
	end
end

-- NMDC chat
dcpp:setListener("chat", "spamfilter", filterChat)

-- ADC chat
dcpp:setListener("adcChat", "spamfilter",
	function(hub, user, text, me_msg)
		return filterChat(hub, user, text)
	end
)

-- NMDC private messages
dcpp:setListener("pm", "spamfilter",
	function(hub, user, text)
		return filterChat(hub, user, text)
	end
)

-- ADC private messages
dcpp:setListener("adcPm", "spamfilter",
	function(hub, user, text)
		return filterChat(hub, user, text)
	end
)

---------------------------------------------------------------------------
-- Chat commands
---------------------------------------------------------------------------

dcpp:setListener("ownChatOut", "spamfilter",
	function(hub, text)
		local cmd, arg = text:match("^/spam%s+(%S+)%s*(.*)")
		if not cmd then return nil end

		cmd = cmd:lower()
		arg = arg and arg:match("^%s*(.-)%s*$") or ""

		if cmd == "add" and arg ~= "" then
			-- Validate pattern
			local ok, err = pcall(string.find, "", arg)
			if not ok then
				hub:addLine("*** Invalid Lua pattern: " .. tostring(err))
				return 1
			end
			table.insert(spamfilter.patterns, arg)
			savePatterns()
			hub:addLine("*** Added spam pattern: " .. arg)
			return 1

		elseif cmd == "del" and arg ~= "" then
			local found = false
			for i, p in ipairs(spamfilter.patterns) do
				if p == arg then
					table.remove(spamfilter.patterns, i)
					found = true
					break
				end
			end
			if found then
				savePatterns()
				hub:addLine("*** Removed spam pattern: " .. arg)
			else
				hub:addLine("*** Pattern not found: " .. arg)
			end
			return 1

		elseif cmd == "list" then
			if #spamfilter.patterns == 0 then
				hub:addLine("*** No spam patterns configured")
			else
				local lines = { "*** Spam patterns:" }
				for i, p in ipairs(spamfilter.patterns) do
					table.insert(lines, string.format("  %d. %s", i, p))
				end
				hub:addLine(table.concat(lines, "\n"))
			end
			return 1

		elseif cmd == "clear" then
			spamfilter.patterns = {}
			savePatterns()
			hub:addLine("*** All spam patterns cleared")
			return 1

		elseif cmd == "stats" then
			hub:addLine(string.format(
				"*** Spam filter: %s | Patterns: %d | Blocked: %d",
				spamfilter.enabled and "on" or "off",
				#spamfilter.patterns, spamfilter.blocked))
			return 1

		elseif cmd == "on" then
			spamfilter.enabled = true
			hub:addLine("*** Spam filter enabled")
			return 1

		elseif cmd == "off" then
			spamfilter.enabled = false
			hub:addLine("*** Spam filter disabled")
			return 1
		end
	end
)

DC():PrintDebug("  ** Loaded spam_filter.lua **")
