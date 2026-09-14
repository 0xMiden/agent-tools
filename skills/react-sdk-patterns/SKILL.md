---
name: react-sdk-patterns
description: Complete guide to building Miden frontends with @miden-sdk/react hooks. Covers MidenProvider setup, query hooks (useAccounts, useAccount, useNotes, useNoteStream, useSyncState, useAssetMetadata, useTransactionHistory, PSWAP lineage queries), mutation hooks (useCreateWallet, useCreateFaucet, useImportAccount, useSend, useMultiSend, useMint, useConsume, useSwap, useBridge, useTransaction, useCreateNetworkNote, PSWAP hooks), chain anchors and previews, transaction stages, signer integration, the error surface, and utility functions. Use when writing, editing, or reviewing Miden React frontend code.
---

# Miden React SDK Patterns

## Package pins

```json
"@miden-sdk/react": "0.16.0-rc.7",
"@miden-sdk/miden-sdk": "0.16.0-rc.7"
```

`@miden-sdk/react` declares `@miden-sdk/miden-sdk` as a peer dependency at `^0.16.0-rc.7` and `react` at `>=18.0.0`. Pin exactly, or use a range that itself names a prerelease: npm excludes prereleases from `"0.16"`, `"^0.16.0"`, `"~0.16.0"` and `"0.16.x"`, so those match nothing.

## SDK Choice

ALWAYS use `@miden-sdk/react` hooks. Only fall back to the raw WASM client (`WasmWebClient`, imported by the React SDK as `WebClient`) via `useMidenClient()` for operations not covered by hooks. The React SDK handles WASM safety, state management (Zustand), auto-sync, and transaction stage tracking.

## MidenProvider Configuration

```tsx
import { MidenProvider } from "@miden-sdk/react";

<MidenProvider
  config={{
    rpcUrl: "testnet",          // "devnet" | "testnet" | "localhost" | "local" | custom URL
    prover: "testnet",          // "local" | "localhost" | "devnet" | "testnet" | custom URL | {url,timeoutMs} | {primary,fallback,...}
    autoSyncInterval: 15000,    // ms, set to 0 (or below) to disable. Default: 15000
    noteTransportUrl: "...",    // optional: for private note delivery
    seed: seedBytes,            // optional: Uint8Array, must be 32 bytes
    proverUrls: { testnet: "...", devnet: "..." },  // optional URL overrides
    proverTimeoutMs: 60000,     // number | bigint
    useWorker: true,            // default true — see below
  }}
  loadingComponent={<Loading />}  // shown during WASM init
  errorComponent={(error) => <Error error={error} />}  // function form receives the Error; a static element does not
>
  <App />
</MidenProvider>
```

There is **no `storeName` config field**. `storeName` lives on `SignerContextValue`; when a signer is connected the IndexedDB name is derived as `` `MidenClientDB_${signer.storeName}` ``.

`useWorker` defaults to `true` (WASM calls run off the main thread). Set it to `false` when you pass a `CallbackProver` — the worker boundary serializes the prover with `TransactionProver.serialize()`, which has no encoding for the callback variant and silently downgrades to `"local"` — or when embedding in a single-WebView native shell (Capacitor host, Tauri, Electron preload).

The object form of `prover` is `{ primary, fallback?, disableFallback?: () => boolean, onFallback?: () => void }`.

| Network | rpcUrl | Resolves to |
|---------|--------|-------------|
| Testnet | `"testnet"` | `https://rpc.testnet.miden.io` — recommended for new projects |
| Devnet | `"devnet"` | `https://rpc.devnet.miden.io` |
| Localhost | `"localhost"` or `"local"` | `http://localhost:57291` |

## Query Hooks

Most return their own result shape plus `isLoading`, `error`, `refetch` — but not uniformly: `useNoteStream` has no `refetch`, `useSyncState` exposes `sync` instead of `refetch`, and `useAccounts` hardcodes `error: null` (fetch failures are only `console.error`-ed).

### useAccounts()
```tsx
const { accounts, wallets, faucets, isLoading, error, refetch } = useAccounts();
// accounts — AccountHeader[] (every tracked account)
// wallets  — @deprecated, mirrors `accounts`
// faucets  — @deprecated, always `[]`
// error    — always null
```

Faucet-vs-wallet is not encoded in the account id, so `wallets` mirrors `accounts` and `faucets` is always empty. Both are marked `@deprecated`. Use `accounts` and detect faucets **per-account** via `account.isFaucet()` (load the full `Account` with `useAccount`).

### useAccount(accountId: AccountRef | undefined)
```tsx
const { account, assets, getBalance, isLoading, error, refetch } = useAccount(accountId);
// account — Account object (.id(), .nonce(), .bech32id(), .isFaucet(), .isNetworkAccount())
// assets — AssetBalance[] { assetId, amount, symbol?, decimals? }
// getBalance(assetId) — bigint balance for a specific token
```

`AccountRef = string | AccountId | Account | AccountHeader` — hex, bech32, or a parsed object.

**`assetId` everywhere in this SDK is a faucet (token) account id string** — `asset.faucetId().toString()`. The React SDK exposes no protocol `AssetId`, `AssetClass` or `AssetVaultKey` type; do not "fix" these names to those.

`account.id()` and `account.nonce()` are methods (call them, then `.toString()` to render). `bech32id()` is installed on the `Account` prototype by the React SDK at module load (`installAccountBech32()`).

### useNotes(filter?)
```tsx
const { notes, consumableNotes, noteSummaries, consumableNoteSummaries, isLoading, error, refetch } = useNotes();
// notes — InputNoteRecord[] (filtered ONLY by `status`)
// consumableNotes — ConsumableNoteRecord[] (filtered ONLY by `accountId`)
// noteSummaries — NoteSummary[] (id, assets, sender) — also filtered by `sender` and `excludeIds`
// consumableNoteSummaries — NoteSummary[] — also filtered by `sender` and `excludeIds`

// Each filter option only narrows specific fields — destructure the one it affects:

// `status` filters the returned `notes` (the only option that does):
const { notes } = useNotes({ status: "committed" });  // "all" | "consumed" | "committed" | "expected" | "processing"
// `accountId` (an AccountRef) filters `consumableNotes` (NOT `notes`):
const { consumableNotes } = useNotes({ accountId: "0x..." });
// `sender` filters only the summary arrays (NOT `notes`/`consumableNotes`):
const { noteSummaries, consumableNoteSummaries } = useNotes({ sender: "0x..." });
// `excludeIds` filters only the summary arrays:
const { noteSummaries, consumableNoteSummaries } = useNotes({ excludeIds: ["0xnote1", "0xnote2"] });
```

### useNoteStream(options?)
```tsx
const { notes, latest, markHandled, markAllHandled, snapshot, isLoading, error } = useNoteStream();
// notes — StreamedNote[] { id, sender, amount, assets, record, firstSeenAt, attachment }
// latest — most recent StreamedNote (convenience), or null
// markHandled(noteId) — exclude a note from future renders
// markAllHandled() — exclude all current notes
// snapshot() — capture { ids: Set<string>, timestamp } for cross-phase filtering
// No refetch.

// Options (status defaults to "committed"):
const { notes } = useNoteStream({ status: "committed", sender: "0x..." });
const { notes } = useNoteStream({ since: Date.now() - 60000 }); // last 60s
const { notes } = useNoteStream({ excludeIds: new Set(["0xnote1"]) }); // Set<string> | string[]
const { notes } = useNoteStream({ amountFilter: (amount) => amount > 100n });
```

### useSyncState()
```tsx
const { syncHeight, isSyncing, lastSyncTime, sync, error } = useSyncState();
await sync(); // Manual sync
```

### useSyncControl()
```tsx
const { pauseSync, resumeSync, isPaused } = useSyncControl();
```
Prefer this over `autoSyncInterval: 0` when you only need to suspend background sync during a long-running operation — manual `useSyncState().sync()` still works while paused.

### useAssetMetadata(assetIds?: string[])
```tsx
const { assetMetadata } = useAssetMetadata([faucetId]); // takes a string[] (NOT a bare string)
// assetMetadata — Map<string, AssetMetadata>
// Each entry: { assetId, symbol?, decimals? }
const meta = assetMetadata.get(faucetId);
// meta.symbol — "TEST"
// meta.decimals — 8
```

Signature is `useAssetMetadata(assetIds: string[] = [])` and the body calls `assetIds.filter(Boolean)`, so a bare string throws a runtime `TypeError`. Pass an array even for a single asset.

### useTransactionHistory(options?)
```tsx
const { records, record, status, isLoading, error, refetch } = useTransactionHistory({ id: txId });
// status: "pending" | "committed" | "discarded" | null
// Options: { id?, ids?, filter?, refreshOnSync? }
//   - `filter` is a TransactionFilter and overrides id/ids
//   - `refreshOnSync` re-fetches after every provider sync. Default: true
```

### PSWAP lineage queries
```tsx
const { lineages, isLoading, error, refetch } = usePswapLineages();
const { lineages } = usePswapLineagesFor(account);            // AccountRef | null | undefined
const { lineage, isLoading, error, refetch } = usePswapLineage(orderId); // string | bigint | null | undefined
// lineage(s) — PswapLineageRecord[] / PswapLineageRecord | null
```

## Mutation Hooks

Most return their own action function plus `error` and `reset` — but not all: `useWaitForCommit` returns only `{ waitForCommit }`, `useWaitForNotes` only `{ waitForConsumableNotes }`, `useCompile` `{ component, txScript, noteScript, isReady }`, and `useSyncControl` `{ pauseSync, resumeSync, isPaused }`. The families differ in their loading/progress fields:
- **Transaction hooks** expose `isLoading` and `stage` (a `TransactionStage`): `useSend`, `useMultiSend`, `useMint`, `useBridge`, `useConsume`, `useSwap`, `useTransaction`, `useCreateNetworkNote`, `usePswapCreate`, `usePswapConsume`, `usePswapCancel`, `usePswapCancelByOrder`.
- **No `stage`**: `useCreateWallet` / `useCreateFaucet` (`isCreating`), `useImportAccount` (`isImporting`), `useExportStore` / `useExportNote` (`isExporting`), `useImportStore` / `useImportNote` (`isImporting`), `usePreview` (`isPreviewing`), `useChainAnchor` (`isCapturing`), `useExecuteProgram` (`isLoading`).

**Transaction stages**: `"idle"` → `"executing"` → `"proving"` → `"submitting"` → `"complete"`

Most transaction hooks resolve to `TransactionResult = { transactionId: string }`. The exceptions are `useSend` (`SendResult = { txId: string; note: Note | null }`) and `useCreateNetworkNote` (`NetworkNoteResult = { txId: string; note: Note }`).

### AuthScheme — pass the numeric value

The React SDK's own contract is the **WASM numeric enum**. `CreateWalletOptions.authScheme`, `CreateFaucetOptions.authScheme`, the `{type:"seed"}` import option and `useSessionAccount`'s `walletOptions.authScheme` are all typed `AuthScheme`, and `DEFAULTS.AUTH_SCHEME` is `AuthScheme.AuthRpoFalcon512`. The members are:

```
AuthEcdsaK256Keccak = 1
AuthRpoFalcon512    = 2
```

There is a catch at runtime. On the browser entry of `@miden-sdk/miden-sdk`, a locally declared `export const AuthScheme = Object.freeze({ Falcon: "falcon", ECDSA: "ecdsa" })` **shadows** the generated WASM binding (a local `export const` beats `export * from …` in ESM). `@miden-sdk/react` re-exports that same binding, so in a browser build `AuthScheme.AuthRpoFalcon512` reads as `undefined` — including inside `DEFAULTS.AUTH_SCHEME` — while `client.newWallet(storageMode, authScheme, initSeed)` and `newFaucet(…, authScheme)` want the numeric enum.

**So pass the numeric literal in browser code:** `authScheme: 2` (Falcon) or `authScheme: 1` (ECDSA). The SDK's own test writes `authScheme: 2 as unknown as AuthScheme`. Do **not** write `AuthScheme.Falcon` / `AuthScheme.ECDSA` as React usage — those friendly strings belong to the high-level `MidenClient` resource API (`client.accounts.create`), not to these hooks. Only the Node entry offers an escape hatch, re-exporting the napi class as `AuthSchemeNative`; the browser entry has none.

### useCreateWallet()
```tsx
const { createWallet, wallet, isCreating, error, reset } = useCreateWallet();
const account = await createWallet({
  storageMode: "private",                   // "private" | "public". Default: "private"
  authScheme: 2,                            // 2 = Falcon (numeric enum — see above)
  initSeed: seedBytes,                      // optional: Uint8Array for a deterministic account id
});
```
`CreateWalletOptions` is exactly `{ storageMode?, authScheme?, initSeed? }` — there is **no** `mutable` field.

### useCreateFaucet()
```tsx
const { createFaucet, faucet, isCreating, error, reset } = useCreateFaucet();
const account = await createFaucet({
  tokenSymbol: "TEST",
  tokenName: "Test Token",                  // optional: defaults to tokenSymbol
  decimals: 8,                              // Default: 8
  maxSupply: 1000000n,                      // bigint | number, coerced with BigInt(...)
  storageMode: "private",                   // "private" | "public". Default: "private"
  authScheme: 2,                            // 2 = Falcon
});
```

### useImportAccount()
```tsx
const { importAccount, account, isImporting, error, reset } = useImportAccount();

// Import by account ID (network lookup) — accountId is an AccountRef:
const account = await importAccount({ type: "id", accountId: "0x..." });

// Import from file — AccountFile | Uint8Array | ArrayBuffer:
const account = await importAccount({ type: "file", file: accountFileOrBytes });

// Import from seed:
const account = await importAccount({
  type: "seed",
  seed: seedBytes,
  authScheme: 2,                            // optional; 2 = Falcon
});
```
This hook calls `assertSignerConnected()` first: with a signer provider mounted but disconnected it throws "Signer is disconnected. Reconnect your wallet to perform transactions."

### useSend()
```tsx
const { send, result, isLoading, stage, error, reset } = useSend();
const { txId, note } = await send({
  from: senderAccountId,   // AccountRef
  to: recipientAccountId,  // AccountRef
  assetId: faucetId,       // AccountRef — the token faucet id
  amount: 1000n,           // bigint | number — OPTIONAL, required only when sendAll is falsy
  noteType: "private",     // "private" | "public". Default: "private"
  recallHeight: 100,       // optional: sender can reclaim after this block
  timelockHeight: 50,      // optional: recipient can consume after this block
  sendAll: true,           // optional: send entire balance of this asset (ignores amount)
  attachment: [1n, 2n],    // optional: bigint[] | Uint8Array | number[]
  skipSync: false,         // optional: skip the pre-send auto-sync. Default: false
  returnNote: false,       // optional: build the note in JS and surface it on result.note
});
```

Combining `attachment` with `recallHeight` or `timelockHeight` **throws**: "recallHeight and timelockHeight are not supported when attachment is provided".

`SendResult.note` is `null` unless `returnNote: true`.

**How private sends are delivered:** for `noteType: "private"` the hook waits for the transaction to commit and then calls `client.sendPrivateOutputNote(noteId, targetAddress)` to push the note details to the recipient over the note-transport layer. The same call happens in `useMultiSend` (once per private recipient) and in `useTransaction` when `privateNoteTarget` is set. Without that step a private note is never delivered — a public note needs no such push.

### useMultiSend()
```tsx
const { sendMany, result, isLoading, stage, error, reset } = useMultiSend();
const { transactionId } = await sendMany({
  from: senderAccountId,
  assetId: faucetId,
  recipients: [
    { to: recipient1, amount: 500n },
    { to: recipient2, amount: 300n, noteType: "public" },          // per-recipient override
    { to: recipient3, amount: 200n, attachment: [1n, 2n, 3n] },    // per-recipient attachment
  ],
  noteType: "private",     // default for all recipients
  skipSync: false,         // optional
});
```
Resolves to `{ transactionId }`, not `{ txId, note }`. Also calls `assertSignerConnected()`.

### useMint()
```tsx
const { mint, result, isLoading, stage, error, reset } = useMint();
const { transactionId } = await mint({
  targetAccountId: recipientId,   // AccountRef
  faucetId: myFaucetId,           // AccountRef
  amount: 10000n,                 // bigint | number
  noteType: "public",             // Default: "private"
});
```

### useConsume()
```tsx
const { consume, result, isLoading, stage, error, reset } = useConsume();
const { transactionId } = await consume({
  accountId: myAccountId,      // typed `string` — one of two options not widened to AccountRef
  notes: [noteId1, noteId2],   // accepts: hex string IDs, NoteId, InputNoteRecord, or Note
});
```

### useSwap()
```tsx
const { swap, result, isLoading, stage, error, reset } = useSwap();
const { transactionId } = await swap({
  accountId: myAccountId,
  offeredFaucetId: tokenA,
  offeredAmount: 100n,
  requestedFaucetId: tokenB,
  requestedAmount: 50n,
  noteType: "private",
  paybackNoteType: "private",
});
```

### PSWAP (partial swaps)
A PSWAP note can be filled by multiple consumers, each taking a proportional share and leaving a remainder note.

```tsx
const { pswapCreate } = usePswapCreate();
// { accountId, offeredFaucetId, offeredAmount, requestedFaucetId, requestedAmount, noteType?, paybackNoteType? }

const { pswapConsume } = usePswapConsume();
await pswapConsume({
  accountId,
  note,              // hex string | NoteId | InputNoteRecord | Note
  fillAmount: 25n,   // requested asset supplied from the consumer's own vault
  noteFillAmount: 0n // optional: supplied by other in-flight notes routed into the same tx. Default 0
});

const { pswapCancel } = usePswapCancel();          // { accountId, note }
const { pswapCancelByOrder } = usePswapCancelByOrder();
await pswapCancelByOrder({ orderId: "123456789" }); // string | bigint — a JS `number` is NOT accepted
```

A PSWAP order id is `u64`-shaped and routinely exceeds `Number.MAX_SAFE_INTEGER`, which is why `number` is rejected. `pswapCancelByOrder` resolves the creator account and the lineage's current tip note from the locally tracked lineage.

### useBridge()
```tsx
const { bridge, result, isLoading, stage, error, reset } = useBridge();
const { transactionId } = await bridge({
  from: senderAccountId,
  bridgeAccount: bridgeAccountId,
  assetId: faucetId,
  amount: 100n,
  destinationNetwork: 1,                    // AggLayer-assigned network id
  destinationAddress: "0xabc...",           // 0x-prefixed Ethereum address
  skipSync: false,                          // optional
});
```
Emits a single public B2AGG (Bridge-to-AggLayer) note that the bridge account consumes, burning the asset so it can be claimed on the destination network.

### useCreateNetworkNote()
```tsx
const { createNetworkNote, result, isLoading, stage, error, reset } = useCreateNetworkNote();
const { txId, note } = await createNetworkNote({
  accountId: senderId,       // AccountRef — creates, funds and submits the note
  target: networkAccountId,  // AccountRef — the network account the note targets
  script: myNoteScript,      // NoteScript — OR `recipient`, exactly one of the two
  recipient: myRecipient,    // NoteRecipient (advanced)
  executionHint,             // optional NoteExecutionHint. Defaults to `always`
  inputs: [1n, 2n],          // optional: note storage / inputs the script reads (used with `script`)
  assetId, amount,           // optional: a single asset to lock into the note
  attachment: [1n, 2n, 3n],  // optional: extra payload appended after the NetworkAccountTarget
});
note.isNetworkNote(); // true
```
Passing both `recipient` and `script`, or neither, throws. The note is always `NoteType.Public`; the `NetworkAccountTarget` attachment — not the tag — is what a network account matches on.

### useTransaction() — Escape Hatch
```tsx
const { execute, result, isLoading, stage, error, reset } = useTransaction();

// With a pre-built TransactionRequest:
const { transactionId } = await execute({ accountId, request: txRequest });

// With a factory function (gets access to the client):
await execute({
  accountId,
  request: (client) => client.newSwapTransactionRequest(/* ... */),
});

// Full option set:
await execute({
  accountId,                       // AccountRef
  request,                         // TransactionRequest | (client) => TransactionRequest
  skipSync: false,                 // optional
  privateNoteTarget: recipientRef, // optional: push private output notes to this account after commit
  anchor,                          // optional ChainAnchor — routes to client.executeTransactionAt
});
```

### useExecuteProgram() — view call
```tsx
const { execute, result, isLoading, error, reset } = useExecuteProgram();
const { stack } = await execute({
  accountId,                 // string | AccountId
  script: txScript,          // compiled TransactionScript
  adviceInputs,              // optional AdviceInputs
  foreignAccounts,           // optional: (string | AccountId | { id, storage? })[]
  skipSync: false,
});
// stack — bigint[] (16 elements). Runs locally; nothing is proven or submitted.
```

### useCompile()
```tsx
const { component, txScript, noteScript, isReady } = useCompile();
// Wraps CompilerResource from @miden-sdk/miden-sdk, so the option shapes are
// identical to MidenClient.compile: CompileComponentOptions,
// CompileTxScriptOptions, CompileNoteScriptOptions.
```

### useChainAnchor() and usePreview()
Since protocol 0.16 a signed `TransactionSummary` binds the reference block commitment, so a summary signed at one block only reproduces when re-executed at that block. Anchors are what let a multisig proposer, its co-signers and the eventual executor agree despite different sync heights.

```tsx
const client = useMidenClient();
const { captureAnchor, anchor, anchoredRequest, isCapturing, error, reset } = useChainAnchor();
const { preview, summary, isPreviewing } = usePreview();

const request = await buildRequest(client);
const chainAnchor = await captureAnchor({ request });
// Use the same resolved request for capture and preview. `anchoredRequest` is
// React state and still has the previous render's value in this callback.
const txSummary = await preview({ accountId, request, anchor: chainAnchor });
```

`preview` produces a summary **only while authorization is pending** — i.e. when the account's auth procedure aborts with the unauthorized event, e.g. a multisig below its signing threshold. A fully authorized transaction produces no summary and the call rejects with `code: "TRANSACTION_ALREADY_AUTHORIZED"`; submit it with `useTransaction` instead. It is not a dry-run confirmation-screen API.

`captureAnchor` rejects with `code: "OPERATION_BUSY"` (a capture is already running), `"STALE_CLIENT"`, or `"INVALID_CHAIN_ANCHOR"` (a sync landed mid-capture — retry). It runs on the main thread and briefly blocks the UI. The caller owns the anchor: `reset()` does not free it, and since it carries a partial blockchain, call `anchor.free()` when done in a repeated-capture flow. Serialize with `anchor.serialize()` and rebuild with `ChainAnchor.deserialize(bytes)` — importing the class from `@miden-sdk/miden-sdk`, since `@miden-sdk/react` re-exports `ChainAnchor` as a type only.

### useWaitForCommit()
```tsx
const { waitForCommit } = useWaitForCommit();
await waitForCommit(result.txId, {  // useSend returns { txId, note }; most other hooks use { transactionId }
  timeoutMs: 10000,   // Default: 10000
  intervalMs: 1000,   // Default: 1000
});
```

### useWaitForNotes()
```tsx
const { waitForConsumableNotes } = useWaitForNotes();
const records = await waitForConsumableNotes({
  accountId: myAccountId,   // AccountRef
  minCount: 1,              // Default: 1
  timeoutMs: 10000,         // Default: 10000
  intervalMs: 1000,         // Default: 1000
});
// resolves to ConsumableNoteRecord[]
```

### useExportStore() / useImportStore() / useExportNote() / useImportNote()
```tsx
const { exportStore, isExporting } = useExportStore();
const snapshot = await exportStore();                       // JSON string of the IndexedDB store

const { importStore, isImporting } = useImportStore();
await importStore(snapshot, storeName, options);

const { exportNote } = useExportNote();
const bytes = await exportNote(noteId);                     // serialized NoteFile bytes

const { importNote } = useImportNote();
const noteId = await importNote(bytes);                     // returns the note id string
```

### useSessionAccount(options)
```tsx
const { initialize, sessionAccountId, isReady, step, error, reset } = useSessionAccount({
  fund: async (sessionId) => {
    // Called after the session wallet is created — fund it here
    await send({ from: mainWallet, to: sessionId, assetId: faucetId, amount: 100n });
  },
  assetId: faucetId,              // optional; reserved for future note filtering — the hook body never reads it
  walletOptions: {                // optional: session wallet creation options
    storageMode: "public",        // "private" | "public". Default: "public"
    authScheme: 2,                // 2 = Falcon
  },
  pollIntervalMs: 3000,           // funding detection interval. Default: 3000
  maxWaitMs: 60000,               // max wait for the funding note. Default: 60000
  storagePrefix: "miden-session", // localStorage key prefix. Default: "miden-session"
});
// Steps: "idle" → "creating" → "funding" → "consuming" → "ready"
// Call initialize() to start the flow. isReady becomes true when fully funded.
```
The session wallet default storage mode is **`"public"`**, unlike `useCreateWallet`'s `"private"`. The hook persists `${storagePrefix}:accountId` and `${storagePrefix}:ready` in `localStorage` and restores them on mount; `reset()` removes both.

## Transaction Progress UI

```tsx
function SendButton({ from, to, assetId, amount }) {
  const { send, stage, isLoading, error } = useSend();

  return (
    <div>
      <button onClick={() => send({ from, to, assetId, amount })} disabled={isLoading}>
        {isLoading ? `${stage}...` : "Send"}
      </button>
      {error && <p>Error: {error.message}</p>}
    </div>
  );
}
```

## Signer Integration

### Local Keystore (Default)
No signer provider needed. Keys are managed in the browser via IndexedDB.

### External Signers
`MidenProvider` reads the nearest ancestor `SignerContext`; when one is present and connected it builds the client with `WebClient.createClientWithExternalKeystore(...)` instead of the local keystore. Three signer providers are used by the SDK's example app:

- `ParaSignerProvider` from `@miden-sdk/para-react`
- `TurnkeySignerProvider` from `@miden-sdk/turnkey-react`
- `MidenFiSignerProvider` from `@miden-sdk/miden-wallet-adapter-react`

All three are published from the web-sdk monorepo. Keep them on the same v0.16 release line as `@miden-sdk/react` and `@miden-sdk/miden-sdk`.

### MultiSignerProvider — the shape the example app uses
For apps offering a choice of signer, wrap everything in `MultiSignerProvider` and mount each signer provider — each containing a `<SignerSlot />` — as a **sibling** of `MidenProvider`:

```tsx
import { MidenProvider, MultiSignerProvider, SignerSlot } from "@miden-sdk/react";
import { ParaSignerProvider } from "@miden-sdk/para-react";
import { TurnkeySignerProvider } from "@miden-sdk/turnkey-react";
import { MidenFiSignerProvider } from "@miden-sdk/miden-wallet-adapter-react";
import { WalletAdapterNetwork } from "@miden-sdk/miden-wallet-adapter-base";

<MultiSignerProvider>
  <ParaSignerProvider apiKey={import.meta.env.VITE_PARA_API_KEY} environment="BETA">
    <SignerSlot />
  </ParaSignerProvider>
  <TurnkeySignerProvider
    config={{ defaultOrganizationId: import.meta.env.VITE_TURNKEY_ORGANIZATION_ID }}
  >
    <SignerSlot />
  </TurnkeySignerProvider>
  <MidenFiSignerProvider network={WalletAdapterNetwork.Testnet} autoConnect={false}>
    <SignerSlot />
  </MidenFiSignerProvider>
  <MidenProvider config={{ rpcUrl: "testnet", prover: "testnet" }}>
    <App />
  </MidenProvider>
</MultiSignerProvider>
```

`SignerSlot` is render-less: it registers its nearest ancestor's `SignerContext` value into the registry. `MultiSignerProvider` forwards only the *active* signer down to `MidenProvider`, so before a user picks one the app runs in local-keystore mode and reads work immediately.

```tsx
const { signers, activeSigner, connectSigner, disconnectSigner } = useMultiSigner() ?? {};
await connectSigner("Turnkey");   // switches active signer and calls its connect()
await disconnectSigner();          // reverts to local keystore mode
```
`useMultiSigner()` returns `null` outside a `MultiSignerProvider`.

### useSigner() — Unified Interface
Returns `SignerContextValue | null` — `null` in local-keystore mode. Guard before destructuring.
```tsx
const signer = useSigner();
if (!signer) return null; // local keystore mode
const { isConnected, connect, disconnect, name } = signer;
```

### Custom Signer
Implement `SignerContextValue` via `SignerContext.Provider`. Required: `name`, `storeName` (unique per user for DB isolation), `accountConfig`, `signCb`, `isConnected`, `connect`, `disconnect`. Optional: `getKeyCb`, `insertKeyCb`. See the `signer-integration` skill for the full contract.

### Wallet-extension detection
```tsx
import { waitForWalletDetection } from "@miden-sdk/react";
import type { WalletAdapterLike } from "@miden-sdk/react";

await waitForWalletDetection(adapter);        // default 5000 ms timeout
await waitForWalletDetection(adapter, 10000);
```
`WalletAdapterLike` is a duck type — `{ readyState: string; on/off("readyStateChange", cb) }` — with no dependency on any wallet-adapter package. It resolves once `readyState === "Installed"`, otherwise rejects with "Wallet extension not detected within …ms".

## Error Surface

```tsx
import { MidenError, wrapWasmError } from "@miden-sdk/react";
import type { CodedError, MidenErrorCode, WasmErrorCode } from "@miden-sdk/react";
```

- `MidenErrorCode` = `"WASM_CLASS_MISMATCH" | "WASM_POINTER_CONSUMED" | "WASM_NOT_INITIALIZED" | "WASM_SYNC_REQUIRED" | "SEND_BUSY" | "OPERATION_BUSY" | "STALE_CLIENT" | "UNKNOWN"` — assigned by this package.
- `WasmErrorCode` = `"INVALID_CHAIN_ANCHOR" | "TRANSACTION_ALREADY_AUTHORIZED"` — assigned by the Rust client.
- `CodedError = Error & { readonly code?: MidenErrorCode | WasmErrorCode | (string & {}) }`.

Branch on `code`, never on message text. On Node, client-assigned codes arrive as a `"CODE: "` prefix on the message rather than a property, because the napi bindings cannot attach one.

## Utility Functions

```tsx
import {
  formatAssetAmount, parseAssetAmount,
  getNoteSummary, formatNoteSummary,
  toBech32AccountId, installAccountBech32, ensureAccountBech32,
  normalizeAccountId, accountIdsEqual,
  readNoteAttachment, createNoteAttachment,
  bytesToBigInt, bigIntToBytes, concatBytes,
  waitForWalletDetection,
  migrateStorage, clearMidenStorage, createMidenStorage,
  DEFAULTS,
} from "@miden-sdk/react";

formatAssetAmount(1000000n, 8)       // "0.01"
parseAssetAmount("0.01", 8)          // 1000000n
toBech32AccountId("0x1234...");      // "mtst1..." (testnet HRP; defaults to testnet)
```

`getNoteSummary(note, getAssetMetadata?)` takes a `ConsumableNoteRecord | InputNoteRecord` and returns `NoteSummary | null` — **`null`** for a note whose id or metadata is not available yet.

`formatNoteSummary(summary, formatAsset?)`: if `summary.assets` is empty it returns `summary.id` alone — no asset text and **no sender suffix**, regardless of `sender`. Otherwise it joins assets with `" + "` and appends `" from <sender>"` when a sender is present.

The bech32 HRP is inferred from the configured `rpcUrl` and defaults to testnet: mainnet `mm`, testnet `mtst` (default), devnet `mdev`, plus a `Custom` network type. There is no `miden` HRP.

`DEFAULTS` is a value export: `{ RPC_URL: undefined, AUTO_SYNC_INTERVAL: 15000, STORAGE_MODE: "private", AUTH_SCHEME: AuthScheme.AuthRpoFalcon512, NOTE_TYPE: "private", FAUCET_DECIMALS: 8 }`.

## Direct Client Access

```tsx
const client = useMidenClient(); // throws if not ready
const { runExclusive, prover, signerAccountId, signerConnected, isReady, isInitializing, error, sync } = useMiden();

// For operations not covered by hooks (use methods on the WebClient itself —
// e.g. getSyncHeight, getAccounts, getTransactions; getBlockHeaderByNumber lives on RpcClient, not here):
await runExclusive(async () => {
  const accounts = await client.getAccounts();
});
```
**The built-in hooks route their client calls through `runExclusive` too** — 22 hook files pull it out of `useMiden()` and wrap every call, using the pattern `const runExclusiveSafe = runExclusive ?? runExclusiveDirect;` so they still serialize when no provider-supplied lock is available. `useSend`, `useMint`, `useConsume`, `useSwap`, `useBridge`, `useTransaction`, `usePreview`, `useChainAnchor`, `useCreateWallet`, `useCreateFaucet`, `useExecuteProgram`, the export/import hooks, `useWaitForNotes` and all four PSWAP hooks do this. Use it for your own multi-step sequences for the same reason they do.

> `MidenProvider.tsx` carries an in-source comment claiming "Built-in hooks no longer use this since the WebClient handles concurrency internally". The hook bodies contradict it — the comment is stale. The WebClient's own serialization is a *separate* layer (see `frontend-pitfalls` FP2), not a replacement for this one.

## Non-surface — do not invent these

- **No dedicated React fee hook or provider option.** For a custom request, obtain the underlying client and call its public `feeAwareTransactionRequestBuilder(account)` instance method.
- **No `AccountDelta` / `AccountPatch` re-export.** The only summary-shaped re-export is `TransactionSummary` (used by `usePreview`).
- **No protocol `AssetId` / `AssetClass` / `AssetVaultKey`.** Every `assetId` here is a faucet account reference.
- **Do not treat the package's own `README.md`, `CLAUDE.md` or `ReactSDK.Arena.Findings.md` as authoritative** — they are stale. The README still documents `authScheme: 0`, a `mutable` wallet option, and `storageMode: 'network'`, none of which exist. `src/types/index.ts` plus the hook bodies are the source of truth.

## Type Imports

```tsx
import { AuthScheme, DEFAULTS, MidenError } from "@miden-sdk/react"; // values, not just types

import type {
  MidenConfig, RpcUrlConfig, ProverConfig, ProverTarget, ProverUrls, MidenState,
  QueryResult, MutationResult, TransactionStage, SyncState,
  AccountsResult, AccountResult, AssetBalance, AccountRef,
  NotesFilter, NotesResult, NoteSummary, NoteAsset, AssetMetadata,
  TransactionHistoryOptions, TransactionHistoryResult, TransactionStatus,
  CreateWalletOptions, CreateFaucetOptions, ImportAccountOptions,
  SendOptions, SendResult, MultiSendOptions, MultiSendRecipient,
  MintOptions, BridgeOptions, ConsumeOptions, SwapOptions,
  CreateNetworkNoteOptions, NetworkNoteResult,
  PswapCreateOptions, PswapConsumeOptions, PswapCancelOptions,
  PswapCancelByOrderOptions, PswapLineageResult, PswapLineagesResult,
  ExecuteTransactionOptions, CaptureAnchorOptions, PreviewTransactionOptions,
  ExecuteProgramOptions, ExecuteProgramResult, TransactionResult,
  WaitForCommitOptions, WaitForNotesOptions,
  StreamedNote, UseNoteStreamOptions, UseNoteStreamReturn,
  UseSessionAccountOptions, UseSessionAccountReturn, SessionAccountStep,
  SignerContextValue, SignCallback, SignerAccountConfig, SignerAccountType,
  MultiSignerContextValue,
  CodedError, MidenErrorCode, WasmErrorCode,
  // SDK types re-exported for convenience:
  WebClient, Account, AccountHeader, AccountId, AccountFile,
  InputNoteRecord, ConsumableNoteRecord, TransactionId, TransactionFilter,
  TransactionRecord, TransactionRequest, TransactionSummary, ChainAnchor,
  NoteType, Note, AccountStorageMode, PswapLineageRecord,
} from "@miden-sdk/react";
```

Note the `…Return` suffix on `UseNoteStreamReturn` and `UseSessionAccountReturn` — every other hook result type uses `…Result` (`UseSendResult`, `UseCreateWalletResult`, `UseChainAnchorResult`, and so on), all exported from the package root.
