--// vim:ts=4:sw=4:noet
--// chat_commands.lua -- Framework for custom /slash commands
--//
--// Usage:
--//   Copy to your scripts directory, or run directly:
--//     eispy lua eval-file examples/lua/chat_commands.lua
--//
--// Built-in commands:
--//   /me <text>       Send an action message (* Nick text)
--//   /slap <nick>     Slap a user with a random object
--//   /coin            Flip a coin
--//   /dice [N]        Roll a die (default 6 sides)
--//   /calc <expr>     Evaluate a simple math expression
--//   /hubinfo         Show hub URL, name, and your nick
--//   /settings <key>  Look up a DC++ setting value
--//   /cmds            List all registered commands

if not chatcmds then
	chatcmds = {}
	chatcmds.handlers = {}
end

-- Register a command.  handler(hub, args_string) should return:
--   nil     to pass through (not handled)
--   1       to consume the input (don't send to hub)
function chatcmds.register(name, description, handler)
	chatcmds.handlers[name:lower()] = {
		desc = description,
		func = handler,
	}
end

---------------------------------------------------------------------------
-- Built-in commands
---------------------------------------------------------------------------

-- /me <text> — action message
chatcmds.register("me", "Send an action message", function(hub, args)
	if args == "" then
		hub:addLine("*** Usage: /me <text>")
		return 1
	end
	hub:sendChat("* " .. hub:getOwnNick() .. " " .. args)
	return 1
end)

-- /slap <nick> — slap somebody
chatcmds.register("slap", "Slap a user with a random object", function(hub, args)
	if args == "" then
		hub:addLine("*** Usage: /slap <nick>")
		return 1
	end
	local objects = {
		"a large trout",
		"a mass-produced paperback book",
		"a mass-produced rubber keyboard",
		"an mass-produced mass-production thingy",
		"a mass-produced mass-production thingy thingamajig",
	}
	local obj = objects[math.random(#objects)]
	hub:sendChat("* " .. hub:getOwnNick() .. " slaps " .. args .. " with " .. obj)
	return 1
end)

-- /coin — flip a coin
chatcmds.register("coin", "Flip a coin", function(hub, args)
	local result = math.random(2) == 1 and "heads" or "tails"
	hub:sendChat("* " .. hub:getOwnNick() .. " flips a coin: " .. result)
	return 1
end)

-- /dice [N] — roll a die
chatcmds.register("dice", "Roll a die (default d6)", function(hub, args)
	local sides = tonumber(args) or 6
	if sides < 2 then sides = 6 end
	local result = math.random(sides)
	hub:sendChat("* " .. hub:getOwnNick() .. " rolls d" .. sides .. ": " .. result)
	return 1
end)

-- /calc <expr> — simple math
chatcmds.register("calc", "Evaluate a math expression", function(hub, args)
	if args == "" then
		hub:addLine("*** Usage: /calc <expression>")
		return 1
	end
	-- Only allow safe characters: digits, operators, parens, dots, spaces
	if args:match("[^%d%s%.%+%-%*/%%%(%)%^]") then
		hub:addLine("*** Invalid expression (only numbers and +-*/%%^() allowed)")
		return 1
	end
	local fn, err = load("return " .. args)
	if fn then
		local ok, result = pcall(fn)
		if ok then
			hub:addLine("*** " .. args .. " = " .. tostring(result))
		else
			hub:addLine("*** Error: " .. tostring(result))
		end
	else
		hub:addLine("*** Parse error: " .. tostring(err))
	end
	return 1
end)

-- /hubinfo — show hub information
chatcmds.register("hubinfo", "Show hub URL, name, and your nick", function(hub)
	hub:addLine(string.format(
		"*** Hub: %s | Name: %s | Protocol: %s | Nick: %s",
		hub:getUrl(),
		hub:getHubName() or "(unknown)",
		hub:getProtocol(),
		hub:getOwnNick()))
	return 1
end)

-- /settings <key> — look up a DC++ setting
chatcmds.register("settings", "Look up a DC++ setting value", function(hub, args)
	if args == "" then
		hub:addLine("*** Usage: /settings <SettingName>")
		return 1
	end
	local val = DC():GetSetting(args)
	if val then
		hub:addLine("*** " .. args .. " = " .. tostring(val))
	else
		hub:addLine("*** Setting not found: " .. args)
	end
	return 1
end)

-- /cmds — list all registered commands
chatcmds.register("cmds", "List all registered commands", function(hub)
	local lines = { "*** Available commands:" }
	local names = {}
	for name in pairs(chatcmds.handlers) do
		table.insert(names, name)
	end
	table.sort(names)
	for _, name in ipairs(names) do
		table.insert(lines, string.format(
			"  /%s  —  %s", name, chatcmds.handlers[name].desc))
	end
	hub:addLine(table.concat(lines, "\n"))
	return 1
end)

---------------------------------------------------------------------------
-- Dispatcher
---------------------------------------------------------------------------

math.randomseed(os.time())

dcpp:setListener("ownChatOut", "chatcmds",
	function(hub, text)
		local cmd, args = text:match("^/(%S+)%s*(.*)")
		if not cmd then return nil end

		cmd = cmd:lower()
		local entry = chatcmds.handlers[cmd]
		if entry then
			return entry.func(hub, args or "")
		end
		-- Unknown command — pass through to other handlers
	end
)

DC():PrintDebug("  ** Loaded chat_commands.lua **")
