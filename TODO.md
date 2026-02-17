# TODO — eiskaltdcpp-py

## Upstream patches needed

### Singleton pattern prevents safe restart (high priority)

The eiskaltdcpp core library uses the Singleton pattern (via
`dcpp::Singleton<T>`) for nearly every manager class:
`SettingsManager`, `ClientManager`, `ConnectionManager`,
`TimerManager`, `ShareManager`, `HashManager`, `QueueManager`,
`SearchManager`, `FavoriteManager`, `CryptoManager`,
`DownloadManager`, `UploadManager`, `DebugManager`, etc.

**The problem:** `dcpp::shutdown()` deletes these singletons, but
several of them do not fully clean up their internal state (threads,
file handles, callbacks, static pointers).  Calling `dcpp::startup()`
again in the same process after a `shutdown()` results in segfaults,
double-frees, or use-after-free because:

1. `TimerManager` starts a thread in `start()` but `shutdown()` may
   not join it reliably before the singleton is destroyed.
2. `HashManager` has background hasher threads that may still reference
   the deleted singleton.
3. `SettingsManager` leaves stale state in static arrays (`isSet[]`,
   default values) that are not reinitialised on the second
   `startup()`.
4. `BufferedSocket` instances hold raw pointers to manager singletons
   that become dangling after `shutdown()`.
5. The Lua `ScriptInstance::L` static pointer is never cleaned up on
   shutdown, and `initLuaScriptingIfPresent()` (our workaround) only
   initialises it once.

**Impact on eiskaltdcpp-py:** Unit tests that each create/destroy a
`DCBridge` (which calls `startup()`/`shutdown()`) crash on the second
test.  We work around this by sharing a single bridge instance per
test class (`scope="class"` fixture), but this is fragile and prevents
proper test isolation.

**Proposed upstream fix:**

- Add a `Singleton<T>::reset()` method that fully reinitialises the
  instance (or make `getInstance()` safely create a new instance after
  `deleteInstance()`).
- Ensure all manager destructors join their threads and flush state.
- Make `dcpp::startup()` idempotent — safe to call after a prior
  `shutdown()` in the same process.
- Consider replacing singletons with a `Context` object that owns all
  managers, so multiple independent instances can coexist (useful for
  testing and embedding).

**Tracking:** Plan to submit a patch to
<https://github.com/eiskaltdcpp/eiskaltdcpp> once the fix is proven
locally.  In the meantime, the workaround is to never call
`shutdown()` + `startup()` more than once per process.

---

## Other items

- [ ] Expose `SettingsManager` int64 and float settings through
      `getSetting()`/`setSetting()` (currently only string and int are
      properly handled).
- [ ] Add Python-level Lua script evaluation API if upstream exposes
      `ScriptManager::EvaluateChunk()` through the shared library.
- [ ] Windows and macOS wheel builds (currently Linux-only).
