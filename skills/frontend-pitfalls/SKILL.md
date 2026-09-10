---
name: frontend-pitfalls
description: Critical pitfalls and safety rules for Miden frontend development. Covers client-readiness gating, WASM concurrency and pointer lifetimes, COOP/COEP for the multi-threaded build, BigInt boundaries, Bech32 network prefixes, IndexedDB loss, auto-sync side effects, the Web Worker shim, structured error codes, eager vs lazy entry points, and Vite configuration. Use when reviewing, debugging, or writing Miden frontend code.
---

# Miden Frontend Pitfalls

Every claim below is verified against `web-sdk` at tag `v0.16.0-rc.7`. Pin exactly:

```json
{
  "dependencies": {
    "@miden-sdk/miden-sdk": "0.16.0-rc.7",
    "@miden-sdk/react": "0.16.0-rc.7"
  }
}
```

Caret/tilde ranges over a plain `0.16.0` (`"^0.16.0"`, `"~0.16.0"`, `"0.16.x"`) do **not** match a prerelease version — npm excludes prereleases from ranges that do not themselves name one. Use the exact string above, or `"^0.16.0-rc.7"` (which is what the SDK's own example wallet uses in `packages/react-sdk/examples/wallet/package.json`).

## FP1: `useMidenClient()` Throws on Render Before the Client Is Ready (HIGH)

`MidenProvider` initializes WASM asynchronously and flips `isReady` only when the client is set. Which hooks that hurts is not uniform, and the distinction is the whole point:

- **Query hooks are safe and self-healing.** `useAccounts`, `useAccount`, `useNotes`, `useTransactionHistory`, … read the Zustand store, and their fetch bodies begin `if (!client || !isReady) return;`. Rendered before readiness they hand back empty arrays / `null` with `error: null` — but their effects are **keyed on `isReady`**, so the moment it flips they refetch on their own. `useAccounts` runs `if (isReady && accounts.length === 0) refetch()` with deps `[isReady, accounts.length, refetch]`; `useNotes` and `useAccount` follow the same shape. You get a brief empty render, not a stuck one, and no `isReady` gate is needed for correctness. (`MidenProvider` in fact fetches accounts *before* calling `setClient`, and its own comment records that `setClient` is what atomically sets `isReady = true`.)
- **Mutation hooks throw only when invoked.** `useSend`, `useMint`, `useConsume`, `useCreateWallet`, `useCreateFaucet`, `useSwap`, … throw `Error("Miden client is not ready")` from inside the mutate call, so an early render is harmless — an early *click* is not.
- **`useMidenClient()` throws on render.** Message: `"Miden client is not ready. Make sure you are inside a MidenProvider and the client has initialized."` This is the one that takes a component down, so any component reaching for the raw client must be gated or mounted below a gate.
- **`useMiden()` throws `"useMiden must be used within a MidenProvider"`** when there is no provider above it.

```tsx
// FINE — renders "0" for one paint, then populates when isReady flips.
// The hook's own effect refetches; no readiness gate is required here.
// Reading isLoading is a UX nicety, not a correctness fix.
function App() {
  const { accounts } = useAccounts();
  return <div>{accounts.length}</div>;
}

// WRONG — throws on the first render pass
function Raw() {
  const client = useMidenClient(); // Error: Miden client is not ready
  return null;
}

// CORRECT — let the provider hold the tree back
<MidenProvider
  config={{ rpcUrl: "testnet" }}
  loadingComponent={<p>Loading WASM...</p>}
  errorComponent={(err) => <p>Init failed: {err.message}</p>}
>
  <App />
</MidenProvider>

// CORRECT — gate explicitly where you need finer control
function App() {
  const { isReady, isInitializing, error } = useMiden();
  if (error) return <p>{error.message}</p>;
  if (!isReady || isInitializing) return <p>Loading...</p>;
  return <WalletView />;
}
```

`loadingComponent` is rendered **only while `isInitializing` is true** and `errorComponent` **only when init failed** — if you pass neither, the provider renders children immediately and you are responsible for the `isReady` gate.

Source: `packages/react-sdk/src/context/MidenProvider.tsx`, `packages/react-sdk/src/hooks/useAccounts.ts`.

## FP2: Interleaving Multi-Step Client Sequences (HIGH)

**A single concurrent call is safe.** The client serializes itself in layers, so `sync()` racing one `client.getAccount()` does not crash:

1. **Layer 1 — in-process call chain.** The `WebClient` wrapper queues WASM calls on a per-instance promise chain (`_serializeWasmCall`). Methods it does not wrap explicitly are still routed onto the chain by its `Proxy` fallback; the only exceptions are the entries in its `SYNC_METHODS` set, which are documented as safe to bind raw. Its own comment names the panic this prevents: `"recursive use of an object detected"` (wasm-bindgen's internal `RefCell`).
2. **Layer 2 — Web Locks.** Exactly three entry points run under `withSyncLock(dbId, methodId, fn)`: `syncState`, `syncChain` and `syncNoteTransport` (on both `WebClient` and `MockWebClient`, so six call sites). It coalesces concurrent calls of the *same* method into one shared promise and serializes *different* methods on the same database — **across browser tabs**. Where the Web Locks API is unavailable it degrades to an in-process per-database promise chain. Note that `fetchPrivateNotes` is **not** among them: it has no JS wrapper, so it gets Layer 1 serialization only, with no Web Lock and no cross-tab coalescing.
3. **Layer 3 — cross-tab state change.** `client.onStateChanged(cb)` (available when `BroadcastChannel` is) fires when another tab mutates the store; `MidenProvider` subscribes and refreshes the Zustand store so the UI re-renders. The client has already auto-synced its own Rust state by then.

On top of that, the client runs its WASM in a Web Worker by default, and the worker's message queue is itself sequential (see FP10).

**What still breaks** is a *sequence* of calls you intended to be atomic. The layers serialize individual calls, not your multi-call flow: another caller (auto-sync, a second hook, another tab) can land between two of your calls. That matters most for WASM object lifetimes. The SDK's own diagnostic for this is `MidenError` with `code: "WASM_POINTER_CONSUMED"`, whose message reads: *"WASM object was already consumed. Some WASM-bound objects can only be passed once — if you need to reuse a value, create a fresh instance before each call."*

`runExclusive` from `useMiden()` is the tool for exactly this. It is an in-React `AsyncLock` (`packages/react-sdk/src/utils/asyncLock.ts`) shared by everything under one `MidenProvider`, and it exists — per its own source comment — "for advanced consumers who need to serialize custom multi-step operations against the client."

Two habits, both taken from how the SDK's own `useSend` is written:

1. **Construct WASM objects inside the exclusive block, one fresh instance per call.** `useSend` creates all its `AccountId` objects inside `runExclusive` with the comment "to avoid stale pointers if another exclusive operation runs between creation and consumption," and re-parses the recipient rather than reusing an earlier instance.
2. **Read out primitives before the call that may invalidate an object.** `useSend` saves the transaction id as a hex string *before* `applyTransaction`, noting that the call "consumes the WASM pointer inside `txResult` (and any child objects like `TransactionId`)."

```tsx
// WRONG — a sync (or another hook, or another tab) can land between the two
// calls, and one WASM object instance is reused across that gap
const client = useMidenClient();
const id = AccountId.fromHex(hex);
const account = await client.getAccount(id);
const notes = await client.getConsumableNotes(id);

// CORRECT — one exclusive block, one fresh instance per call
const { runExclusive } = useMiden();
const { account, notes } = await runExclusive(async () => ({
  account: await client.getAccount(AccountId.fromHex(hex)),
  notes: await client.getConsumableNotes(AccountId.fromHex(hex)),
}));
```

Most built-in mutation hooks already route their client calls through this same `runExclusive`, so hook-driven mutations serialize against each other. Reach for `runExclusive` yourself when you mix direct `useMidenClient()` calls with hook mutations, or when a sequence of raw client calls must not be interleaved.

`MidenProvider.sync()` is deliberately **not** wrapped in `runExclusive` — the client's own layers cover it.

Source: `crates/web-client/js/index.js`, `crates/web-client/js/syncLock.js`, `packages/react-sdk/src/context/MidenProvider.tsx`, `packages/react-sdk/src/utils/asyncLock.ts`, `packages/react-sdk/src/hooks/useSend.ts`, `packages/react-sdk/src/utils/errors.ts`.

## FP3: COOP/COEP Headers — Only for the Multi-Threaded (MT) Build (HIGH)

Cross-origin isolation is **not** a universal requirement. Both `@miden-sdk/miden-sdk` and `@miden-sdk/react` publish four entry points on two axes (eager/lazy × ST/MT) — `.`, `./lazy`, `./mt`, `./mt/lazy` — and the requirement follows the threading model:

- The **default** entries (`@miden-sdk/react`, `@miden-sdk/react/lazy`, `@miden-sdk/miden-sdk`, `@miden-sdk/miden-sdk/lazy`) ship **single-threaded (ST)** WASM that, in the SDK README's words, "loads in any browser context" — **no COOP/COEP required**. The SDK's own example wallet runs `MidenProvider` off the default `@miden-sdk/react` with a bare `midenVitePlugin()` and no isolation.
- The **MT** entries (`/mt`, `/mt/lazy`, wasm-bindgen-rayon, ~3–5× faster local proving) load **only** on a page where `self.crossOriginIsolated === true`. Without `Cross-Origin-Opener-Policy: same-origin` + `Cross-Origin-Embedder-Policy: require-corp` the browser refuses to construct shared memory and `__wbg_init` throws `WebAssembly.Memory: shared memory requires crossOriginIsolated` (or a browser-specific variant).

Pick ST (the default) and you need no headers. Opt into MT only for local proving on a host whose headers you control. With the default worker-backed client, the worker initializes its own pool automatically when the page is isolated and multiple hardware threads are available. Call `initThreadPool(n)` manually only for a direct current-thread MT client with `useWorker: false` (or no worker support), and do so in that client's realm.

If you do opt into MT, request isolation explicitly; the plugin default is `false` (see FP8):

```ts
// vite.config.ts — only needed for the MT build
import { midenVitePlugin } from "@miden-sdk/vite-plugin";

export default defineConfig({
  plugins: [react(), midenVitePlugin({ crossOriginIsolation: true })],
});
```

The plugin injects headers into the Vite **dev and preview servers only**. Set the same headers at your production host. See `vite-wasm-setup` for per-host configs.

**Gotcha (when isolation is on)**: `require-corp` blocks every cross-origin resource that does not carry `Cross-Origin-Resource-Policy: cross-origin` or CORS — remote images, fonts, iframes, third-party scripts — and `same-origin` COOP nullifies `window.opener`, which breaks OAuth popup flows (this is exactly why the SDK's example wallet leaves isolation off: it pairs `midenVitePlugin()` with `paraVitePlugin()`). If you cannot set headers at all, the SDK README points at the `gzuidhof/coi-serviceworker` shim as a deliberate opt-in, not a bundled feature. Do not enable isolation globally as a convenience — scope it to the routes that actually load MT.

Source: `crates/web-client/README.md`, `crates/web-client/package.json`, `packages/react-sdk/package.json`, `packages/react-sdk/examples/wallet/vite.config.ts`.

## FP4: BigInt at the Low-Level `WasmWebClient` Boundary (HIGH)

`number` does **not** fail at the React hook layer, and it does not fail at the high-level `MidenClient` layer either:

- React SDK option types take `bigint | number`: `SendOptions.amount`, `MintOptions.amount`, `SwapOptions.offeredAmount` / `requestedAmount`, `CreateFaucetOptions.maxSupply`, … and hooks coerce (`useCreateFaucet` calls `BigInt(options.maxSupply)`).
- The high-level `MidenClient` resource API also declares `number | bigint` and coerces internally: `SendOptions.amount` and `MintOptions.amount` on `client.transactions`, `FaucetCreateOptions.maxSupply` on `client.accounts.create({ type: AccountType.FungibleFaucet, ... })`, and the swap/pswap amounts.

Strict `bigint` applies only at the **low-level `WasmWebClient`** methods — `newSendTransactionRequest`, `newMintTransactionRequest`, `newSwapTransactionRequest`, etc. — which take a `JsU64` with no coercion.

```tsx
// FINE — React hooks and the high-level MidenClient coerce number → bigint
await send({ from, to, assetId, amount: 1000 });
await createFaucet({ maxSupply: 1000000, ... });

// PREFERRED everywhere — bigint avoids precision loss above 2^53
await send({ from, to, assetId, amount: 1000n });

// REQUIRED — low-level WasmWebClient methods take bigint only.
// (sender, target, faucetId, noteType, amount, recallHeight?, timelockHeight?)
await client.newSendTransactionRequest(fromId, toId, faucetId, noteType, 1000n);

// CORRECT — user input is a decimal string, not a number
import { parseAssetAmount } from "@miden-sdk/react";
const amount = parseAssetAmount(inputValue, 8); // (input: string, decimals?: number) => bigint
```

Prefer `bigint` regardless: a `number` above `2^53` has already lost precision before it reaches the coercion, so large supplies and amounts must be `bigint` or a decimal string through `parseAssetAmount`. Render with `formatAssetAmount`.

**Gotcha**: `JSON.stringify` cannot serialize `bigint`. Use a replacer or stringify first. The SDK's `StorageResult.toJSON()` returns a string for precisely this reason, and its `valueOf()` throws `RangeError` above `Number.MAX_SAFE_INTEGER`.

Source: `packages/react-sdk/src/types/index.ts`, `packages/react-sdk/src/utils/amounts.ts`, `crates/web-client/js/types/api-types.d.ts`, `crates/web-client/js/types/index.d.ts`.

## FP5: Bech32 Network Mismatch (HIGH)

Bech32 account addresses carry a human-readable prefix (HRP) that identifies the network. The real HRPs are:

| Network | HRP | Example address shape |
|---------|-----|-----------------------|
| Mainnet | `mm` | `mm1...` |
| Testnet | `mtst` | `mtst1...` |
| Devnet | `mdev` | `mdev1...` |
| Custom | operator-chosen prefix | — |

There is no `miden1...` prefix. A `mdev1...` address used against testnet points at a different or nonexistent account.

```tsx
// WRONG — a network-specific address baked into a constant
const ADMIN = "mtst1..."; // breaks the moment the app points at devnet

// CORRECT — hex for constants, it is network-agnostic
const ADMIN = "0x1234567890abcdef";

// CORRECT — derive bech32 for display, per network
account.bech32id(); // installed on Account.prototype by @miden-sdk/react
```

Both hex and bech32 are accepted everywhere hooks take an account reference. Prefer hex for constants, bech32 for display.

**Gotcha — the HRP is inferred from your `rpcUrl` string, not from the chain.** `bech32id()` lowercases the resolved `rpcUrl` and looks for the substrings `devnet`/`mdev`, `mainnet`, then `testnet`/`mtst`; **anything else falls back to testnet.** `MidenConfig.rpcUrl` resolves the shorthands `"testnet"`, `"devnet"` and `"localhost"`/`"local"` to concrete URLs and passes any other value through verbatim — so a private RPC endpoint whose hostname contains none of those substrings (or `"localhost"`, which resolves to `http://localhost:57291`) will silently render `mtst1...` addresses. If you run a custom or local network, do not treat `bech32id()` output as authoritative; key off hex.

Source: `protocol:v0.16.0-rc.9:crates/miden-protocol/src/address/network_id.rs`, `crates/web-client/src/models/account_id.rs`, `packages/react-sdk/src/utils/accountBech32.ts`, `packages/react-sdk/src/utils/network.ts`.

## FP6: Auto-Sync Side Effects (MEDIUM)

`DEFAULTS.AUTO_SYNC_INTERVAL` is `15000` (15 seconds). Each sync writes to the Zustand store, and every query hook subscribed to it re-renders.

```tsx
// PROBLEM — form state resets every 15s because the parent re-renders
<MidenProvider config={{ rpcUrl: "testnet" }}>
  <SendForm />
</MidenProvider>

// SOLUTION 1 — preferred: stable keys and memoization
const MemoizedForm = React.memo(SendForm);

// SOLUTION 2 — pause sync for the duration of a sensitive interaction
const { pauseSync, resumeSync, isPaused } = useSyncControl();

// SOLUTION 3 — last resort: disable auto-sync entirely and drive it yourself
<MidenProvider config={{ rpcUrl: "testnet", autoSyncInterval: 0 }}>
```

Prefer `useSyncControl()` over `autoSyncInterval: 0` for transient stability: it toggles a store flag, manual `useSyncState().sync()` still works while paused, and you do not have to rebuild your own sync loop. It is also the right lever during long local proving, where sync would otherwise compete for the WASM queue.

Source: `packages/react-sdk/src/types/index.ts`, `packages/react-sdk/src/hooks/useSyncControl.ts`, `packages/react-sdk/src/store/MidenStore.ts`.

## FP7: IndexedDB State Loss (MEDIUM)

The client persists accounts, keys, notes and transaction history in IndexedDB. Two distinct ways to lose all of it:

1. **The user or the browser deletes it** — "Clear site data", private browsing, storage pressure.
2. **An SDK version bump deletes it.** On open, `ensureClientVersion` compares the running client version against the one stored in the database. If the running version's **major or minor** is higher, the store closes, `delete()`s and reopens empty. Patch upgrades are preserved and handled by Dexie migrations; a minor upgrade is a deliberate nuke tied to network resets. **Upgrading the SDK across a minor version destroys every locally-stored account, key and note on every user's device.**

Mitigations:

- Warn users that clearing browser data deletes their wallet.
- Ship backup/restore *before* you ship an SDK minor upgrade. The surface is `useExportStore()` / `useImportStore()` in `@miden-sdk/react`, backed by the standalone `exportStore(storeName)` / `importStore(storeName, dump)` from `@miden-sdk/miden-sdk`. Per-object export/import also exists on the high-level client (`accounts.export` / `accounts.import`, `notes.export` / `notes.import`).
- Consider external signers (Para, Turnkey, wallet adapters) for production — the key material lives outside the browser store, so only cached chain state is lost.
- Each signer identity gets its own database (`MidenClientDB_<storeName>`), so `SignerContextValue.storeName` must be unique per user.

Source: `crates/idxdb-store/src/ts/schema.ts`, `packages/react-sdk/src/hooks/useExportStore.ts`, `packages/react-sdk/src/hooks/useImportStore.ts`, `packages/react-sdk/src/context/MidenProvider.tsx`.

## FP8: Vite Configuration (MEDIUM)

Use `@miden-sdk/vite-plugin` rather than hand-rolling WASM config. The bare call is correct for the default ST build:

```ts
import { midenVitePlugin } from "@miden-sdk/vite-plugin";

export default defineConfig({
  plugins: [react(), midenVitePlugin()],
});
```

It accepts **four** options:

| Option | Source default | Purpose |
|--------|----------------|---------|
| `wasmPackages` | `["@miden-sdk/miden-sdk"]` | Packages to alias, dedupe, and exclude from pre-bundling |
| `crossOriginIsolation` | `false` | Emit COOP `same-origin` + COEP `require-corp` on the dev **and** preview servers. Set `true` only for the MT build (FP3) |
| `rpcProxyTarget` | `"https://rpc.testnet.miden.io"` | gRPC-web dev proxy target; `false` disables the proxy |
| `rpcProxyPath` | `"/rpc.Api"` | Path prefix the proxy intercepts |

**Do not trust the plugin README on `crossOriginIsolation`.** At `v0.16.0-rc.7` the README documents the default as `true`; the executable source is `false`. The source is correct.

Everything else the plugin does — `build.target: "esnext"`, `optimizeDeps.exclude`, `resolve.dedupe` (including React and `@miden-sdk/react`), the esbuild externalization that keeps React context identity intact, worker format — is covered in `vite-wasm-setup`, along with production host configs for Nginx, Vercel and Cloudflare. Go there rather than duplicating it here.

Source: `packages/vite-plugin/src/index.ts`, `packages/vite-plugin/README.md`.

## FP9: React StrictMode Double-Init (LOW)

React StrictMode double-invokes effects in development (React 18+; the React SDK's peer dep is `react >= 18.0.0`). `MidenProvider` guards against it with an `isInitializedRef` plus a `cancelled` flag, and wraps the whole init in `runExclusive` so a second mount queues behind an in-flight init instead of racing it. Manual low-level `createClient()` calls have no such guard and will initialize twice.

Naming, so you know what you are holding:

- `@miden-sdk/miden-sdk` exports a high-level `MidenClient` — the recommended entry point.
- The low-level client is the class named `WebClient` in source, exported under the alias `WasmWebClient`. Its type declaration is marked `@internal` and says "Low-level WebClient wrapper. Use MidenClient instead."
- The React SDK does its own low-level init via `import { WasmWebClient as WebClient } from "@miden-sdk/miden-sdk"`, and `useMidenClient()` returns that object.

```tsx
// WRONG — manual low-level client creation in an effect; runs twice in dev
useEffect(() => {
  const client = await WasmWebClient.createClient(url);
}, []);

// CORRECT — always use MidenProvider
<MidenProvider config={{ rpcUrl: "testnet" }}>
```

If you genuinely need the low-level constructors, the signatures are:

```ts
WasmWebClient.createClient(
  rpcUrl?, noteTransportUrl?, seed?, storeName?, logLevel?, useWorker?
): Promise<WasmWebClient>

WasmWebClient.createClientWithExternalKeystore(
  rpcUrl?, noteTransportUrl?, seed?, storeName?,
  getKeyCb?, insertKeyCb?, signCb?, logLevel?, useWorker?
): Promise<WasmWebClient>
```

There is no debug-mode argument and no `ClientOptions.debugMode`.

Source: `packages/react-sdk/src/context/MidenProvider.tsx`, `packages/react-sdk/src/index.ts`, `crates/web-client/js/types/index.d.ts`, `packages/react-sdk/package.json`.

## FP10: The Web Worker Shim Silently Downgrades Callback Provers (HIGH)

`useWorker` defaults to **`true`**: the client spawns a Web Worker and dispatches WASM calls to it, keeping the main thread responsive. That is the right default in browsers and extensions — but the worker boundary serializes the prover argument via `TransactionProver.serialize()`, and **that format has no encoding for `newCallbackProver(jsFn)`, so it silently downgrades to the local prover.** Your callback never fires and nothing errors.

```tsx
import { TransactionProver } from "@miden-sdk/miden-sdk";

// WRONG — the worker serializes this prover, loses the callback, proves locally
const prover = TransactionProver.newCallbackProver(nativeProveFn);
<MidenProvider config={{ rpcUrl: "testnet" }}>

// CORRECT — opt out of the worker so the prover handle reaches WASM intact
<MidenProvider config={{ rpcUrl: "testnet", useWorker: false }}>
```

Set `useWorker: false` when:

- You pass a prover built with `TransactionProver.newCallbackProver(jsFn)` (a native iOS/Android prover behind a Capacitor plugin, or any JS-side prover bridge).
- You are embedding in a single-WebView native shell (Capacitor host, Tauri, Electron preload) where the UI thread is not competing with WASM anyway.

Note that a callback prover is **not** expressible through `MidenConfig.prover` / `ClientOptions.proverUrl` — neither accepts one. `ClientOptions.proverUrl` is a **string only** (`"local" | "devnet" | "testnet"` or a raw remote-prover URL); only `MidenConfig.prover` takes the object forms (`{ url, timeoutMs }` / `{ primary, fallback }`), and its target set also includes `"localhost"`. A `CallbackProver` object has to be handed to the prove call directly.

`MidenConfig.useWorker` is forwarded to both `createClient` and `createClientWithExternalKeystore`. `MidenClient.lastAuthError()` is in the same boat: under the worker shim the sign callback fires against the worker's WASM instance while the accessor reads the main-thread one, so it always returns `null` unless `useWorker: false`.

Note that `usePreview()` runs the VM on the **main thread** regardless — it is not offloaded to the worker — so it blocks the UI for its duration and queues other client calls behind it.

Source: `crates/web-client/js/index.js`, `crates/web-client/js/client.js`, `packages/react-sdk/src/types/index.ts`, `packages/react-sdk/src/context/MidenProvider.tsx`, `packages/react-sdk/src/hooks/usePreview.ts`.

## FP11: Branch on `error.code`, Never on Message Text (MEDIUM)

Errors carry machine-readable codes. Message strings are not a stable API.

- Codes assigned by the React SDK (`MidenError`, closed union `MidenErrorCode`): `WASM_CLASS_MISMATCH`, `WASM_POINTER_CONSUMED`, `WASM_NOT_INITIALIZED`, `WASM_SYNC_REQUIRED`, `SEND_BUSY`, `OPERATION_BUSY`, `STALE_CLIENT`, `UNKNOWN`.
- Codes assigned by the Rust client and thrown out of WASM (`WasmErrorCode`): `INVALID_CHAIN_ANCHOR`, `TRANSACTION_ALREADY_AUTHORIZED`. This list is deliberately **not** exhaustive of what the client can emit — `CodedError.code` includes a `(string & {})` arm so codes from a newer client stay assignable. Handle the ones you care about and fall through on the rest.

```tsx
import type { CodedError } from "@miden-sdk/react";

try {
  await preview({ ... });
} catch (e) {
  const err = e as CodedError;
  if (err.code === "TRANSACTION_ALREADY_AUTHORIZED") {
    await execute({ ... }); // nothing to authorize — just submit it
  }
}
```

**Gotcha — `preview()` is not a dry run of the happy path.** `usePreview()` / `client.transactions.preview()` returns a `TransactionSummary` **only while authorization is still pending** (e.g. a multisig below its threshold, where the auth procedure aborts with the unauthorized event). A fully authorized transaction produces no summary and **rejects** with `code: "TRANSACTION_ALREADY_AUTHORIZED"`. A confirmation screen built on "preview then submit" will hit the rejection on every ordinary single-signature send. Use `useTransaction().execute` to submit.

**Gotcha — on Node the code prefixes the message** instead of being a property, because the napi bindings cannot attach one.

`WASM_CLASS_MISMATCH` almost always means multiple copies of `@miden-sdk/miden-sdk` are bundled — fix it with `resolve.dedupe` + `optimizeDeps.exclude` (which `midenVitePlugin()` already does; see FP8).

Source: `packages/react-sdk/src/utils/errors.ts`, `packages/react-sdk/src/hooks/usePreview.ts`, `crates/web-client/js/types/api-types.d.ts`.

## FP12: The Eager Entry Hangs Under Capacitor and SSR (MEDIUM)

The default browser entry (`@miden-sdk/miden-sdk`) awaits WASM at **module top level**, so any wasm-bindgen constructor is safe to call on the next line with no readiness gate. That top-level await is a liability in two hosts:

- **Capacitor / WKWebView**: the `capacitor://localhost` scheme handler hangs module evaluation on top-level await indefinitely.
- **Next.js / SSR**: top-level await blocks server-side module evaluation.

Import `@miden-sdk/miden-sdk/lazy` (or `@miden-sdk/react/lazy`) there — identical API surface, no top-level await — and await `MidenClient.ready()` before touching wasm-bindgen types. Under `@miden-sdk/react` the provider's `isReady` already is that gate.

Source: `crates/web-client/js/eager.js`, `crates/web-client/package.json`.

## Quick Reference

| # | Pitfall | Severity | One-Line Rule |
|---|---------|----------|---------------|
| FP1 | Client not ready | HIGH | Query hooks are safe — they self-heal when `isReady` flips. `useMidenClient()` throws on render; gate that one |
| FP2 | Interleaved sequences | HIGH | Single calls self-serialize; wrap multi-call sequences in `runExclusive` and rebuild WASM objects inside it |
| FP3 | COOP/COEP | HIGH | Default ST build needs no headers; required ONLY for the `/mt` entries |
| FP4 | BigInt | HIGH | Hooks and `MidenClient` coerce `number`; strict `bigint` only at low-level `WasmWebClient`. Prefer `bigint` |
| FP5 | Bech32 prefix | HIGH | HRPs are `mm` / `mtst` / `mdev` — never `miden1`. Hex for constants, bech32 for display |
| FP6 | Auto-sync | MEDIUM | Default 15000ms; prefer `useSyncControl()` over `autoSyncInterval: 0` |
| FP7 | IndexedDB loss | MEDIUM | A minor SDK bump wipes the store — ship `useExportStore`/`useImportStore` before upgrading |
| FP8 | Vite config | MEDIUM | `midenVitePlugin()` has four options; `crossOriginIsolation` really defaults to `false` |
| FP9 | StrictMode | LOW | Use `MidenProvider`, not manual `WasmWebClient.createClient()` |
| FP10 | Worker shim | HIGH | `useWorker` defaults `true` and silently downgrades callback provers — set `false` when you supply one |
| FP11 | Error handling | MEDIUM | Branch on `error.code`, never message text; `preview()` rejects on already-authorized transactions |
| FP12 | Eager entry | MEDIUM | Use `/lazy` under Capacitor and SSR — top-level await hangs there |
