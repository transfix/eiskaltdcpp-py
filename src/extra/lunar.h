/*
 * Minimal stub for extra/lunar.h
 *
 * The system-installed dcpp/ScriptManager.h includes "extra/lunar.h" which
 * is not shipped by libeiskaltdcpp-dev.  We only need the Lunar<T> template
 * to exist so that ScriptManager.h compiles — our code never calls any
 * Lunar methods.
 *
 * The primary reason we need ScriptManager.h at all is that when the system
 * library is compiled with LUA_SCRIPT, the Client class inherits from
 * ClientScriptInstance -> ScriptInstance, which adds a vtable pointer and
 * changes the ABI layout of all dcpp::Client members.  Our bridge code MUST
 * be compiled with the same LUA_SCRIPT setting to match.
 */

#pragma once

extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
}

template <typename T>
class Lunar {
public:
    typedef int (T::*mfp)(lua_State *L);
    typedef struct { const char *name; mfp mfunc; } RegType;

    static void Register(lua_State *) { /* stub — implemented in library */ }
};
