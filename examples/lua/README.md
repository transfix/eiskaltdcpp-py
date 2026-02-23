# Example Lua Scripts for eiskaltdcpp-py

These scripts demonstrate the eiskaltdcpp Lua scripting API.  They
require `startup.lua` (shipped with eiskaltdcpp) and a client compiled
with `LUA_SCRIPT=ON`.

## Installation

Copy scripts to your config scripts directory:

```bash
# See where scripts live
eispy lua status

# Copy one or more scripts
cp examples/lua/*.lua ~/.eiskaltdcpp-py/scripts/

# Or run them directly
eispy lua eval-file examples/lua/chat_logger.lua
```

## Scripts

| Script | Description |
|--------|-------------|
| `chat_logger.lua` | Log all hub chat to timestamped files |
| `auto_greet.lua` | Welcome users who join with a configurable message |
| `chat_commands.lua` | Framework for custom `/slash` commands |
| `hub_monitor.lua` | Track hub connect/disconnect events and user counts |
| `spam_filter.lua` | Block messages matching configurable keyword patterns |

## API quick reference

Scripts interact with eiskaltdcpp through the `dcpp` listener system
and the `DC()` object:

```lua
-- Register a listener
dcpp:setListener("chat", "myId", function(hub, user, text)
    -- hub:getUrl(), hub:sendChat(msg), hub:addLine(msg)
    -- user:getNick(), user:isOp()
    -- return 1 to suppress the message, nil to pass through
end)

-- DC() singleton
DC():PrintDebug("message")           -- debug log
DC():GetSetting("Nick")              -- read a setting
DC():GetConfigPath()                 -- config dir
DC():GetScriptsPath()                -- scripts dir
DC():SendHubMessage(hub:getId(), raw)-- send raw protocol data
DC():RunTimer(1)                     -- enable 1-second timer
```

See the [project README](../../README.md#lua-scripting) for the full
API reference.
