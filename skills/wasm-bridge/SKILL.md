---
name: wasm-bridge
description: Enforce conventions for the Rust<->JavaScript WASM boundary in the web-sdk repo (crate miden-client-web at crates/web-client, split out of miden-client). Use when exposing Rust methods to JS via the #[js_export] proc-macro, creating newtype wrappers, handling errors across the boundary with JsErr, bridging JS Promises to Rust Futures, or layering the public MidenClient resource API on top of the WASM-bound WebClient.
---

# WASM Bridge Patterns (web-client / miden-client-web)

The web client lives in the dedicated **web-sdk** repo
(`github.com/0xMiden/web-sdk`), split out of `miden-client`. The Rust<->JS
boundary crate is `crates/web-client` (cargo package `miden-client-web`,
`crate-type = ["cdylib"]`). Companion workspace crates: `crates/js-export-macro`
(the `#[js_export]` proc-macro), `crates/idxdb-store` (`miden-idxdb-store`, the
IndexedDB store), `crates/mobile-prover` (`miden-mobile-prover`, a C-ABI native
prover for iOS/Android Capacitor plugins), and `tools/strip-masp-debug`.

The crate dual-targets two binding technologies from one Rust source:
- **browser** (the `browser` feature) via `wasm_bindgen`, error type `JsValue`
- **Node.js** (the `nodejs` feature) via `napi` / `napi-derive`, error type
  `napi::Error`

A platform abstraction layer in `crates/web-client/src/platform.rs` provides
type aliases and helpers so most code is written once. Key aliases:

- `JsErr` — the platform error type (`wasm_bindgen::JsValue` on browser,
  `napi::Error` on nodejs). Two constructors: `from_str_err(msg: &str) -> JsErr`
  and `from_str_err_with_code(msg: &str, code: &str) -> JsErr`.
- `JsU64` — `u64` on browser, `napi::bindgen_prelude::BigInt` on nodejs; both
  surface as a JS `BigInt`. Convert with `js_u64_to_u64` / `u64_to_js_u64`.
- `JsBytes` — `js_sys::Uint8Array` on browser, `napi::bindgen_prelude::Buffer`
  on nodejs. Convert with `bytes_to_js` / `js_to_bytes`.
- `AsyncCell<T>` — interior mutability: `RefCell` on browser, `tokio::sync::Mutex`
  on nodejs; `.lock().await` yields a `DerefMut` guard. The browser branch also
  exposes a synchronous `.borrow() -> std::cell::Ref<'_, T>`, used by
  `#[wasm_bindgen(getter)]` methods that cannot be async.
- `maybe_wrap_send` — pass-through on browser; on nodejs it unsafely asserts
  `Send` on a future so napi's multi-threaded tokio runtime accepts it. Wrap
  boxed client futures with it before `.await` in dual-platform methods.

## Exposing Rust Methods to JavaScript

### Method Annotation — `#[js_export]`

The public API is exposed with the custom `#[js_export]` proc-macro from the
`js-export-macro` crate, **not** raw `#[wasm_bindgen]`. `#[js_export]` generates
the dual `wasm_bindgen` (browser) and `napi` (Node.js) annotations from one
attribute, forwarding `constructor` / `js_name` / `getter`. When a signature
contains `JsU64`, the macro splits the impl per platform, replacing `JsU64` with
`u64` (browser) or `BigInt` (nodejs) — so `JsU64` is resolved by the macro and
does not need to be imported in the annotated module. Raw `#[wasm_bindgen]` is
reserved for browser-only members (e.g. synchronous getters that cannot be async).

Apply `#[js_export]` to the struct/enum/impl block, and `#[js_export(js_name =
"camelCase")]` to each method to map snake_case Rust to camelCase JS:

```rust
use js_export_macro::js_export;

use crate::models::account_header::AccountHeader;
use crate::platform::{JsErr, from_str_err};
use crate::{WebClient, js_error_with_context};

#[js_export]
impl WebClient {
    #[js_export(js_name = "getAccounts")]
    pub async fn get_accounts(&self) -> Result<Vec<AccountHeader>, JsErr> {
        let mut guard = self.get_mut_inner().await;
        let client = guard
            .as_mut()
            .ok_or_else(|| from_str_err("Client not initialized"))?;

        let result = client
            .get_account_headers()
            .await
            .map_err(|err| js_error_with_context(err, "failed to get accounts"))?;

        Ok(result.into_iter().map(|(header, _)| header.into()).collect())
    }
}
```

Rules:
- Annotate with `#[js_export]` (struct/impl) and `#[js_export(js_name = ...)]`
  (methods). Use `#[js_export(constructor)]` for constructors,
  `#[js_export(getter)]` for getters. Use raw `#[wasm_bindgen]` only for
  browser-only items.
- Methods take `&self` (the inner client is behind an `AsyncCell`/lock, so no
  `&mut self`). Acquire the client with `let mut guard =
  self.get_mut_inner().await;` then `let client = guard.as_mut().ok_or_else(||
  from_str_err("Client not initialized"))?;`. `get_mut_inner` returns a
  `DerefMut` guard over `Option<Client<ClientAuth>>`.
- Return `Result<T, JsErr>` — never `Result<T, JsValue>` directly, and never
  panic across the boundary.
- Use `.map_err(|err| js_error_with_context(err, "context"))` for all fallible
  client calls.
- Convert return types via `.into()` (implement `From` on wrapper types).

## Error Handling Across the Boundary

### js_error_with_context

Use the `js_error_with_context` helper (in `crates/web-client/src/lib.rs`) to
chain error sources and attach hints. It returns `JsErr` and splits per
platform; the browser branch additionally attaches a stable machine-readable
`code`:

```rust
pub(crate) fn js_error_with_context<T>(err: T, context: &str) -> JsErr
where
    T: Error + 'static,
{
    let error_message = build_error_chain(context, &err);
    let help = hint_from_error(&err);

    #[cfg(feature = "browser")]
    {
        let js_error: JsValue = JsError::new(&error_message).into();
        if let Some(help) = help {
            let _ = Reflect::set(&js_error, &JsValue::from_str("help"), &JsValue::from_str(&help));
        }
        // Stable, machine-readable code for the ClientError variants JS callers
        // branch on, so they don't have to match the (changeable) message text.
        // The worker shim's serializeError forwards both `code` and `help`.
        if let Some(code) = code_from_error(&err) {
            let _ = Reflect::set(&js_error, &JsValue::from_str("code"), &JsValue::from_str(code));
        }
        js_error
    }

    #[cfg(feature = "nodejs")]
    {
        let message = match help {
            Some(help) => format!("{error_message} [help: {help}]"),
            None => error_message,
        };
        napi::Error::from_reason(message)
    }
}
```

This:
1. Chains all error sources into one message via `build_error_chain(context,
   &err)` (walks `err.source()`, writing `context: err1: err2: ...`).
2. Extracts an `ErrorHint` from `ClientError` via `hint_from_error` if available.
3. Browser path: attaches `help` (the hint) and `code` (from `code_from_error`)
   as properties on the JS `Error` via `Reflect::set`.
4. Node.js path: returns `napi::Error::from_reason(...)` with the help inlined
   into the message.

### Stable Error Codes

JS callers branch on a `code`, never on message text. Two primitives produce one:

- `code_from_error` (consulted inside `js_error_with_context`) maps
  `ClientError::AccountNotFoundOnChain` to `ACCOUNT_NOT_FOUND_ON_CHAIN` and
  `ClientError::AccountAlreadyTracked` to `ACCOUNT_ALREADY_TRACKED`, recursing
  through `err.source()`.
- `from_str_err_with_code(msg, code)` (in `platform.rs`) attaches a code to an
  error built from a plain string. Currently used for
  `TRANSACTION_ALREADY_AUTHORIZED` (raised by `execute_for_summary` /
  `execute_for_summary_at` when execution produced no summary because the
  transaction was already fully authorized) and `INVALID_CHAIN_ANCHOR` (from
  `ClientError::ChainAnchorError`, routed through `map_anchor_err`).

The two platforms surface the code differently, and consumers must handle both:

```rust
// browser: a `code` property on the JS Error object
let js_error: wasm_bindgen::JsValue = wasm_bindgen::JsError::new(msg).into();
let _ = js_sys::Reflect::set(
    &js_error,
    &wasm_bindgen::JsValue::from_str("code"),
    &wasm_bindgen::JsValue::from_str(code),
);

// nodejs: napi's error `code` is its fixed Status enum, so the stable code is
// prefixed onto the message instead: "<CODE>: <message>"
napi::Error::from_reason(format!("{code}: {msg}"))
```

When you add a code, add it to this vocabulary deliberately — it is a public
contract. Do not document a code for an error path that does not actually reach
it (`map_anchor_err` carries an explicit comment about exactly that).

### Error Pattern in Every Method

```rust
client
    .some_operation()
    .await
    .map_err(|err| js_error_with_context(err, "failed to <describe operation>"))?;
```

The context string should be lowercase and describe the failed operation. For
the not-initialized guard, build the error with `from_str_err("Client not
initialized")` (the platform helper), not `JsValue::from_str(...)`.

## Newtype Wrappers

### Pattern

Wrap native Miden types in thin newtypes for JS exposure, annotated with
`#[js_export]`. Fallible construction returns `Result<Self, JsErr>`:

```rust
use js_export_macro::js_export;
use miden_client::{Felt as NativeFelt, Word as NativeWord};
use crate::platform::{JsBytes, JsErr, from_str_err, js_u64_to_u64, u64_to_js_u64};

#[derive(Clone)]
#[js_export]
pub struct Word(NativeWord);

#[js_export]
impl Word {
    /// Creates a word from four numeric values.
    ///
    /// Each input must be a canonical field element, i.e. strictly less than the
    /// field modulus. `Felt::new` errors out on inputs at or beyond the modulus;
    /// the error is surfaced to JS.
    #[js_export(constructor)]
    pub fn new(u64_vec: Vec<JsU64>) -> Result<Word, JsErr> {
        if u64_vec.len() != 4 {
            return Err(from_str_err(&format!(
                "Word requires exactly 4 elements, got {}",
                u64_vec.len()
            )));
        }
        let fixed_array_u64: [u64; 4] = u64_vec
            .into_iter()
            .map(js_u64_to_u64)
            .collect::<Vec<u64>>()
            .try_into()
            .expect("length checked above");
        let native_felt_vec: [NativeFelt; 4] = fixed_array_u64
            .iter()
            .map(|&v| NativeFelt::new(v))
            .collect::<Result<Vec<NativeFelt>, _>>()
            .map_err(|err| from_str_err(&format!("invalid field element: {err}")))?
            .try_into()
            .expect("length checked above");
        Ok(Word(native_felt_vec.into()))
    }

    #[js_export(js_name = "fromHex")]
    pub fn from_hex(hex: String) -> Result<Word, JsErr> {
        let native_word = NativeWord::try_from(hex.as_str())
            .map_err(|err| from_str_err(&format!("Error instantiating Word from hex: {err}")))?;
        Ok(Word(native_word))
    }
}
```

Notes:
- `JsU64` (BigInt-aware) is used for numeric inputs, not `u64`, so full 64-bit
  precision survives the JS `Number`/`BigInt` boundary. The `#[js_export]` macro
  rewrites `JsU64` per platform, so it is referenced unqualified and is not
  imported alongside the `js_u64_to_u64` / `u64_to_js_u64` converters.
- `NativeFelt::new` is **fallible** — it returns a `Result` and rejects values at
  or beyond the field modulus. Propagate that failure; do not `.unwrap()` it.
- Constructors that can fail (length checks, `Felt::new`) return
  `Result<_, JsErr>`.
- `from_hex` takes `String` (not `&str`) and returns `Result<Word, JsErr>`.

### Felt on the JS side vs. the Rust side

The Rust `Felt` newtype (`crates/web-client/src/models/felt.rs`) is
`Felt(NativeFelt)` with `pub fn new(value: JsU64) -> Result<Felt, JsErr>`,
`as_int() -> JsU64`, and `to_string() -> String`. On the JS side that surfaces
as a class taking a single **`BigInt`**, not a number and not an array:

```javascript
const felt = new Felt(42n);        // BigInt argument; throws on non-canonical values
const value = felt.asInt();        // BigInt back out
const felts = word.toFelts();      // Felt[] from a Word
const word = Word.newFromFelts([f0, f1, f2, f3]);
```

Passing a JS `Number` where `JsU64` is expected is a boundary bug — every
`JsU64` parameter and return is a `BigInt` in JS on both platforms.

### Required Conversions and Accessors

Implement the `From` conversions, and put the internal `as_native` accessor in a
**plain** `impl` block (not under `#[js_export]`, since it is `pub(crate)`):

```rust
impl Word {
    pub(crate) fn as_native(&self) -> &NativeWord {
        &self.0
    }
}

// Native -> Wrapper (by value and by ref)
impl From<NativeWord> for Word {
    fn from(native_word: NativeWord) -> Self { Word(native_word) }
}
impl From<&NativeWord> for Word {
    fn from(native_word: &NativeWord) -> Self { Word(*native_word) }
}

// Wrapper -> Native (by value and by ref)
impl From<Word> for NativeWord {
    fn from(word: Word) -> Self { word.0 }
}
impl From<&Word> for NativeWord {
    fn from(word: &Word) -> Self { word.0 }
}
```

For wrapper newtypes that must be accepted as by-value or `Vec<T>` parameters on
the Node.js side, also invoke `impl_napi_from_value!(Word);` (defined twice with
`#[cfg]` gates in `crates/web-client/src/miden_array.rs`: the nodejs version
implements `FromNapiValue` by delegating to `FromNapiRef` and cloning, the
browser version expands to nothing). It bridges napi-rs v3's missing
`FromNapiValue` for `#[napi]` class types.

### Factory Methods

Provide `fromHex()`-style constructors that return `Result<Self, JsErr>` for
user-facing types.

### Keeping the JS API stable across a Rust rename

When an upstream Rust API is renamed or its semantics change, keep the JS name
and adapt inside the wrapper rather than breaking JS callers.
`crates/web-client/src/models/account_builder.rs` is the model:

- `AccountBuilder::build()` calls upstream `build_with_schema_commitment()`, so
  the default JS `build()` now merges the storage-schema-commitment component.
  `buildWithoutSchemaCommitment()` is exposed for the legacy behaviour.
- `withAuthComponent` is a back-compat shim whose body forwards to
  `with_component`, because upstream removed `with_auth_component` and now
  identifies the auth component by its `@auth_script` MASM attribute.

Similarly, when an upstream type is added rather than replaced, wrap both and
keep them. `models/account_patch/{mod,storage,vault}.rs` wrap `AccountPatch` /
`AccountStoragePatch` / `AccountVaultPatch` (absolute post-transaction state),
while `models/account_delta/` survives because `TransactionSummary.accountDelta()`
still returns a relative delta. Both directories coexist deliberately — do not
delete one as "superseded".

## Data Transfer Objects

For complex data that crosses the WASM boundary, use a dual-platform
`getter_with_clone` / `napi(object)` struct (gated with `cfg_attr`), and map
field names with browser-side `js_name`:

```rust
// crates/web-client/src/models/account_storage.rs
#[cfg_attr(feature = "browser", wasm_bindgen(getter_with_clone, inspectable))]
#[cfg_attr(feature = "nodejs", napi(object))]
#[derive(Clone)]
pub struct StorageMapEntry {
    #[cfg_attr(feature = "browser", wasm_bindgen(js_name = "root"))]
    pub root: String,
    #[cfg_attr(feature = "browser", wasm_bindgen(js_name = "key"))]
    pub key: String,
    #[cfg_attr(feature = "browser", wasm_bindgen(js_name = "value"))]
    pub value: String,
}
```

Rules:
- Use the dual-platform `#[cfg_attr(feature = "browser", wasm_bindgen(...))]` +
  `#[cfg_attr(feature = "nodejs", napi(object))]` form — never a bare
  `#[wasm_bindgen(getter_with_clone)]`.
- `getter_with_clone` auto-generates JS getters; `inspectable` improves console
  inspection. `inspectable` can also stand alone (without `getter_with_clone`)
  on an opaque wrapper class, again via the dual form `#[cfg_attr(feature =
  "browser", wasm_bindgen(inspectable))]` + `#[cfg_attr(feature = "nodejs",
  napi)]` (note: bare `napi`, not `napi(object)`, for a class that wraps a
  native handle rather than a plain-data object). See `models/address.rs`,
  `models/code_builder.rs`, and the array wrappers in `miden_array.rs`.
- Field names: snake_case in Rust, camelCase via browser-side `js_name`.
- Serialize complex values to hex strings or `JsBytes`/`Vec<u8>` where needed.

## Promise Handling (idxdb-store pattern)

When calling JS functions from Rust that return Promises (the IndexedDB store,
in `crates/idxdb-store`), use these helpers (`crates/idxdb-store/src/promise.rs`):

```rust
/// Awaits a JavaScript `Promise` and returns the raw `JsValue` on success.
pub(crate) async fn await_js_value(promise: Promise, ctx: &str) -> Result<JsValue, StoreError> {
    JsFuture::from(promise)
        .await
        .map_err(|js_error| StoreError::DatabaseError(format!("{ctx}: {js_error:?}")))
}

/// Awaits a JavaScript `Promise` and deserializes the result into `T`.
pub(crate) async fn await_js<T>(promise: Promise, ctx: &str) -> Result<T, StoreError>
where
    T: DeserializeOwned,
{
    let js_value = await_js_value(promise, ctx).await?;
    from_value(js_value)
        .map_err(|err| StoreError::DatabaseError(format!("failed to deserialize ({ctx}): {err:?}")))
}

/// Awaits a JavaScript `Promise` and discards the result.
pub(crate) async fn await_ok(promise: Promise, ctx: &str) -> Result<(), StoreError> {
    let _ = await_js_value(promise, ctx).await?;
    Ok(())
}
```

Rules:
- Always provide a context string describing what the await is for.
- Use `await_js::<T>()` when you need to deserialize the result.
- Use `await_ok()` when you only care about success/failure.
- Use `serde_wasm_bindgen::from_value()` for deserialization, not `serde_json`.
- Import `Promise` as `use wasm_bindgen_futures::js_sys::Promise;` in this
  module (the store re-exports it through `wasm_bindgen_futures` rather than
  depending on `js_sys` directly there).

### The account forest is Rust-side, not Dexie-side

`crates/idxdb-store/src/forest.rs` holds `AccountForest`: an in-memory
`AccountSmtForest<ForestInMemoryBackend>` with a monotonic `VersionId`, rebuilt
from the account tables on every store open. It exists because the forest
`Backend` trait is synchronous while every IndexedDB access from WASM goes
through a JS promise. Asset and storage-map **witnesses** are served from this
forest, not from Dexie. Updates are forward-only — there is no staging or
rollback; recovery is `IdxdbStore::rebuild_account_forest`. Don't add a
promise-backed path for witness reads.

## Importing JS Functions from Rust

Declare external JS functions with `#[wasm_bindgen(module = "...")]` (browser /
idxdb-store side):

```rust
#[wasm_bindgen(module = "/src/js/utils.js")]
extern "C" {
    #[wasm_bindgen(js_name = logWebStoreError)]
    fn log_web_store_error(error: JsValue, error_context: alloc::string::String);
}

#[wasm_bindgen(module = "/src/js/schema.js")]
extern "C" {
    /// Opens the database and registers it in the JS registry.
    #[wasm_bindgen(js_name = openDatabase)]
    fn open_database(network: &str, client_version: &str) -> js_sys::Promise;
}
```

Rules:
- Module path is relative to the crate root.
- Function names are snake_case in Rust, mapped via `js_name`.
- Return `js_sys::Promise` for async operations.
- Pass simple types across the boundary: `&str`, `JsValue`, `Vec<u8>`, `u32`.

## JS Layers

`crates/web-client/js/` holds several modules. Two are the layers you extend:

1. **`WebClient`** (`js/index.js`) — the WASM-bound class re-exported as
   `WasmWebClient` (`export { WebClient as WasmWebClient, MockWebClient as
   MockWasmWebClient, MockWebClient, withSyncLock }`). It wraps the `WebClient`
   Rust struct and adds JS-side concerns:
   - `_serializeWasmCall` queue that linearizes WASM calls (the inner client is
     behind a lock, so the JS side must not interleave async calls).
   - `withSyncLock(dbId, methodId, fn)` (`js/syncLock.js`, Web Locks via
     `navigator.locks`; also exports `hasWebLocks`) to coalesce concurrent syncs
     and serialize them across tabs. Sync-family methods nest the two:
     `return await withSyncLock(dbId, methodId, async () =>
     this._serializeWasmCall(...))`.
   - method-classification sets (`SYNC_METHODS`, `READ_METHODS`,
     `WRITE_METHODS`) enforced by `scripts/check-method-classification.js`.
     `SYNC_METHODS` is a historical misnomer — it groups methods forwarded
     transparently to the WASM through `createClientProxy`, i.e. that need no
     explicit JS-class wrapper; it does not mean "synchronous".
     `WRITE_METHODS` / `READ_METHODS` exist solely for the CI lint
     (`void WRITE_METHODS; void READ_METHODS;`).
   - the Web Worker shim (below).
2. **`MidenClient`** (`js/client.js`) — the public, resource-based wrapper that
   owns a `WebClient` instance and exposes **eight** typed sub-objects:
   `client.accounts`, `client.transactions`, `client.notes`, `client.tags`,
   `client.settings`, `client.compile` (a `CompilerResource`, hence the property
   is `compile` though the file is `compiler.js`), `client.keystore`, and
   `client.pswap` (a `PswapResource`). Each resource lives under
   `js/resources/<name>.js`.

Supporting modules in the same directory: `eager.js` (top-level-await entry),
`wasm.js` (loader), `standalone.js` (tree-shakeable note/tag builders),
`storageView.js`, `constants.js`, `asyncLock.js`, `webLock.js`, `syncLock.js`,
`utils.js`, `node-index.js` + `node/` (the napi entry), and
`workers/web-client-methods-worker.js`.

`index.js` injects the WASM constructor and the `getWasm` initializer into
`MidenClient` via static fields to break the import cycle:

```javascript
MidenClient._WasmWebClient = WebClient;
MidenClient._MockWasmWebClient = MockWebClient;
MidenClient._getWasmOrThrow = getWasmOrThrow;
```

### Array wrappers consume their elements

There is **no** `safe-arrays.js` module. The wasm-bindgen array wrappers are
generated by the `declare_js_miden_arrays!` macro (defined in
`crates/web-client/src/miden_array.rs`, invoked in
`crates/web-client/src/models/mod.rs`), which produces twelve types:
`AccountArray`, `AccountIdArray`, `ForeignAccountArray`, `NoteRecipientArray`,
`NoteArray`, `OutputNoteArray`, `StorageSlotArray`,
`TransactionScriptInputPairArray`, `FeltArray`, `NoteAndArgsArray`,
`NoteDetailsAndTagArray`, `NoteIdAndArgsArray`.

Their constructor **consumes** its elements. To keep an element usable
afterwards, construct the array empty and `push` by reference instead of passing
elements to the constructor:

```javascript
// NoteArray constructor consumes its elements; use push(&note) to keep
// `note` valid so it can be returned to the caller.
const ownOutputs = new wasm.NoteArray();
ownOutputs.push(note);
```

### The Web Worker shim

A Web Worker is spawned **by default**: `ClientOptions.useWorker` defaults to
`true`, and the worker runs the WASM off the main thread. Two knobs govern it:

- `WebClient.workerMode` — a static, default `"auto"`, with values
  `"auto" | "module" | "classic"`. `"auto"` picks `classic` on Safari/WKWebView
  (where module workers cold-start very slowly) and `module` everywhere else,
  by sniffing `navigator.userAgent`. `"module"` forces the `.module.js`
  ES-module worker, required for webpack 5 / Next.js consumers so the asset
  tracer can see the WASM URL. `"classic"` forces the `.js` classic-script
  worker. Set it before the first `WebClient.createClient(...)` call.
- `ClientOptions.useWorker: false` — skips the shim entirely and calls the
  wasm-bindgen `WebClient` on the current thread. **Required for callback
  provers**: the worker boundary serializes the prover with
  `TransactionProver.serialize()`, which has no encoding for
  `newCallbackProver(jsFn)` and silently downgrades it to `"local"`, so the
  callback never fires. Also the right choice in single-WebView native shells
  (Capacitor, Tauri, Electron preload). `lastAuthError()` is likewise meaningful
  only with `useWorker: false`, because the worker's keystore lives in the
  worker's WASM instance.

Both `new Worker(new URL("...", import.meta.url), ...)` call sites in
`js/index.js` are spelled out literally and duplicated on purpose: webpack 5's
new-worker detector is purely syntactic, and hoisting either URL into a variable
downgrades it to a plain asset copy, which makes the worker's dynamic
`import("./Cargo-*.js")` 404. Do not refactor that duplication away.

The worker entry is `js/workers/web-client-methods-worker.js`; its message
vocabulary lives in `js/constants.js` (`WorkerAction`, `CallbackType`,
`MethodName`). On the MT build the worker is also where `wasm.initThreadPool(n)`
is called, via the `INIT` / `INIT_MOCK` actions with `numThreads` plumbed
through.

### Node entry re-exports and name shadowing

`js/node-index.js` is generated by `scripts/gen-node-reexports.js` and
CI-checked by `check:node-reexports`. Three names are excluded from generation
because plain-JS frozen-object enum consts shadow the napi classes:
`WebClient` (re-exported wrapped as `WasmWebClient`), `AccountType`, and
`AuthScheme` — for which the napi class is re-exported by hand as
**`AuthSchemeNative`**. The browser entry (`js/index.js`) has the same shadowing
(`AccountType`, `AuthScheme`, `NoteVisibility`, `StorageMode`, `Linking` are all
`Object.freeze({...})` consts) but exposes **no** `AuthSchemeNative` alias. When
you add a JS-side enum const, check whether it collides with a generated class
name and update the generator's exclusion list.

### Adding a method

When extending the SDK, choose the layer based on whether the work is
**Rust-side** or **glue/shape**:

- **Rust-side logic** (new RPC call, new transaction request type, storage
  access): expose a method on the WASM `WebClient` impl with `#[js_export(js_name
  = "camelCase")]`, then surface it from the matching resource in
  `js/resources/`. Update the method-classification sets in `index.js` so the
  linter (`scripts/check-method-classification.js`) accepts it.
- **JS-side ergonomics** (option-bag normalization, account-ref resolution, type
  coercion): keep the work in the resource module and call the existing WASM
  method.

Resource methods follow this shape:

```javascript
// crates/web-client/js/resources/accounts.js
async get(ref) {
  this.#client.assertNotTerminated();
  const wasm = await this.#getWasm();
  const id = resolveAccountRef(ref, wasm);   // accepts string | AccountId | Account | AccountHeader
  const account = await this.#inner.getAccount(id);
  return account ?? null;
}
```

Rules:

- Always call `this.#client.assertNotTerminated()` at entry. It throws
  `Error("Client terminated")` up front, instead of letting a late call on a
  torn-down client reach a freed wasm handle — where wasm-bindgen traps with
  "null pointer passed to rust", an error that reads like an unrelated bug.
  `CompilerResource` uses the optional-chaining form
  `this.#client?.assertNotTerminated()` because it can be constructed standalone.
- Resolve account/note/storage refs through the helpers in
  `crates/web-client/js/utils.js`, imported from a resource as `../utils.js`, so
  callers can pass any natural form (hex, bech32 address, WASM type). The full
  set is `resolveAccountRef`, `resolveAddress`, `resolveNoteType`,
  `resolveStorageMode`, `resolveAuthScheme`, `resolveNoteIdHex`,
  `resolveTransactionIdHex`, and `hashSeed`. (There is no `utils.js` inside
  `js/resources/` — that directory holds only the eight resource files:
  accounts, compiler, keystore, notes, pswap, settings, tags, transactions.)
- Return WASM-owned objects (e.g. `Account`, `AccountHeader`) directly when
  callers will use them again — wrapping them in plain JS DTOs forces another
  WASM round-trip and breaks identity for code that compares by reference.

### `_withInnerWebClient(fn)` — the `@internal` escape hatch

`MidenClient._withInnerWebClient(fn)` runs `fn` with exclusive access to the
proxied JS `WebClient`, so `fn` can reach lower-level methods
(`executeTransaction`, `proveTransaction[WithProver]`, `submitProvenTransaction`,
`applyTransaction`, `newSendTransactionRequest`, ...). It is intended for
splitting the bundled execute -> prove -> submit -> apply pipeline across
contexts — e.g. an MV3 extension that executes in its service worker, proves in
a `chrome.offscreen` document, then submits and applies back in the SW.

The callback runs inside `_serializeWasmCall`, and while it runs the client's
`_withInnerLockDepth` counter is bumped so that `_serializeWasmCall` invocations
made *by* `fn` run inline instead of enqueuing behind the outer slot (which is
itself awaiting `fn`) — a re-entrant-lock deadlock otherwise.

**Safety contract:** callers MUST hold their own external mutex preventing
concurrent access to the same client instance during `fn`. External callers
queue behind the outer slot, but if one runs during an `await` inside `fn` it
sees `_withInnerLockDepth > 0` and runs inline, racing wasm-bindgen's borrow
check. The method is marked `@internal`; the proxied client's shape is not part
of the documented public API. Pin the SDK version if you depend on it.

## Build Gates

A bridge change must satisfy the repo's generated-artifact checks, all under
`crates/web-client/scripts/` unless noted: `check-method-classification.js`,
`check-bindgen-types.js`, `check-standalone-types.js`, `build-types.js`,
`gen-node-reexports.js`, `verify-release-mt.mjs`, plus repo-level
`scripts/check-react-sdk-sync.js` and the version-parity scripts.

Note that production builds run `tools/strip-masp-debug` via
`crates/web-client/scripts/wasm-opt-with-masp-strip.sh`, removing MASM source
spans and `assert.err` message text from the embedded Miden packages (ST binary
27.4 MB -> 18.8 MB). A failed VM assertion in a production build therefore
reports its error code without the human-readable message; build with
`MIDEN_WEB_DEV=true` when you need full diagnostics.
