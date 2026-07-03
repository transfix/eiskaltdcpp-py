# TODO — eiskaltdcpp-py

## Resolved: Singleton restart hazard (fixed in our fork)

> **Status: RESOLVED.** This used to be the top upstream blocker. Our
> `transfix/eiskaltdcpp` fork removed the singleton pattern entirely: a
> `dcpp::DCContext` object now owns every manager
> (`SettingsManager`, `ClientManager`, `ConnectionManager`,
> `TimerManager`, `ShareManager`, `HashManager`, `QueueManager`,
> `SearchManager`, `FavoriteManager`, `CryptoManager`,
> `DownloadManager`, `UploadManager`, `DebugManager`, …) via dependency
> injection. No class inherits the old `Singleton<>` CRTP base anymore,
> and that header has been deleted.

**What this means for the bindings:**

- Multiple independent `DCContext` instances can coexist in one process,
  so creating/destroying a `DCBridge` per test no longer crashes on the
  second instance.
- `startup()`/`shutdown()` cycles are bounded by the lifetime of a
  `DCContext` rather than process-global singletons, so they no longer
  leave dangling static pointers.
- The `scope="class"` shared-bridge test fixture is no longer required
  for correctness (it can stay for speed, but proper per-test isolation
  is now possible).

The only remaining remnant on the C++ side is the `dcpp::getContext()`
compatibility shim (a single `DCContext*` set once at startup — **not** a
singleton). Removing it is deferred polish tracked in
`eiskaltdcpp/GETCONTEXT_REMOVAL_PLAN.md` (Phase 7–8) and does not affect
the bindings.

---

## Other items

- [ ] **Recover in-process multi-client integration tests.** Now that
      `DCContext` isolation works, bring back the original
      two-client-in-one-process integration tests that verify PM
      exchange, mutual user-list visibility, file-list browsing, and
      file downloads between Alice and Bob. The original tests are
      preserved in git history (commit `5ac0d76`). Until they are
      restored, multi-client scenarios are covered by the
      subprocess-based tests in `tests/test_integration.py`
      (`TestMultiClient*` classes).
- [ ] Expose `SettingsManager` int64 and float settings through
      `getSetting()`/`setSetting()` (currently only string and int are
      properly handled).
- [ ] Add Python-level Lua script evaluation API if upstream exposes
      `ScriptManager::EvaluateChunk()` through the shared library.
- [ ] Windows and macOS wheel builds (currently Linux-only).
