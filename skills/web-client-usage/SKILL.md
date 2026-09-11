---
name: web-client-usage
description: Conventions for writing JavaScript/TypeScript code that uses the Miden web SDK (`@miden-sdk/miden-sdk`). Use when building apps on Miden, writing integration tests, or calling MidenClient methods — covers initialization, the resource-based API (accounts, transactions, notes, pswap, keystore, compile), sync ordering, type conversions, transaction flows, chain anchors, custom contracts, private note transport, and pitfalls.
---

# Web SDK Usage Patterns

This skill targets the `@miden-sdk/miden-sdk` npm package published from
[`0xMiden/web-sdk`](https://github.com/0xMiden/web-sdk). The workspace is
version `0.16.0-rc.7` and builds on the `miden-client` Rust crate at
`0.16.0-rc.5` (`Cargo.toml`). For React-hook usage, prefer the
`react-sdk-patterns` skill — only fall through to the raw client when a hook
does not cover what you need.

## Installing

These are pre-release versions. A range like `"0.16"`, `"^0.16.0"` or
`"0.16.x"` does **not** match a prerelease — npm excludes prereleases from
ranges that do not themselves name one. Pin exactly:

```json
{
  "dependencies": {
    "@miden-sdk/miden-sdk": "0.16.0-rc.7",
    "@miden-sdk/react": "0.16.0-rc.7"
  }
}
```

## API Overview

The SDK exposes a top-level `MidenClient` whose state is split across eight
typed **resources**:

| Resource | What it covers |
|----------|----------------|
| `client.accounts` | Wallets, faucets, custom contracts, listing, import/export, addresses |
| `client.transactions` | `send` / `mint` / `bridge` / `consume` / `consumeAll` / `swap` / `execute` / `createNetworkNote` / `pswapCreate` / `pswapConsume` / `pswapCancel` / `preview` / `submit` / `submitProven` / `executeRequest` / `captureAnchor` / `batch` / `submitBatch` / `executeProgram` / `list` / `waitFor` |
| `client.notes` | Listing, fetching, importing/exporting, private-note transport |
| `client.pswap` | Partial-swap lineage queries and cancel-by-order |
| `client.tags` | Note-tag subscriptions |
| `client.settings` | Persistent client settings |
| `client.compile` | Compiling MASM into account components, tx scripts, note scripts |
| `client.keystore` | Inserting / fetching / removing secret keys |

`MidenClient` is the public surface. The underlying WASM-bound class is
exported as `WasmWebClient` (an alias for `WebClient`) for low-level
operations the resource API does not yet wrap. Some low-level methods have no
`MidenClient` equivalent at all (e.g. `pruneAccountHistory`).

`#inner` is a true JS private field and is unreachable from outside the class.
There is an escape hatch, `client._withInnerWebClient(fn)`, but it is marked
**`@internal`** and comes with a safety contract — read this before using it:

- **It is not a stable API.** The shape of the proxied client is deliberately
  outside the documented public surface and may change between SDK versions.
  Pin the SDK and retest the lower-level surface on every upgrade.
- **Its intended use is narrow**: splitting the bundled
  execute → prove → submit → apply pipeline across execution contexts — the
  motivating case is a Chrome MV3 extension that executes in the service
  worker, proves in a `chrome.offscreen` document (where wasm-bindgen-rayon can
  spawn real threads), then submits and applies back in the worker.
- **You must hold your own external mutex** around all access to that client
  instance for the duration of `fn`. The callback runs inside
  `_serializeWasmCall`, and while it runs the client's `_withInnerLockDepth` is
  bumped so that calls made *by* `fn` run inline instead of enqueuing (without
  that, they would deadlock behind the slot that is awaiting `fn`). The
  consequence is the trap: if an unrelated task runs during one of `fn`'s
  `await`s and calls into the SDK, it also sees `_withInnerLockDepth > 0`, runs
  inline, and races wasm-bindgen's borrow check. The chain does not protect you
  there — your own mutex has to.
- **Do not let references escape** the callback; the lock is released when `fn`
  settles.

If you just need a method the resource API hasn't wrapped, prefer asking for it
upstream over building on this. See `wasm-bridge` for the full mechanism.

## Client Initialization

### Convenience constructors (recommended)

```typescript
import { MidenClient } from "@miden-sdk/miden-sdk";

// Testnet — injects rpcUrl/proverUrl/noteTransportUrl "testnet" and autoSync: true
const client = await MidenClient.createTestnet();

// Devnet equivalent
const client = await MidenClient.createDevnet();
```

Both accept the same `ClientOptions` for overrides:

```typescript
const client = await MidenClient.createTestnet({
  storeName: "my-app-tests",      // isolates the IndexedDB store
  proverUrl: "local",             // prove locally instead of remote
  autoSync: false,                // disable initial sync
});
```

### Generic constructor

```typescript
const client = await MidenClient.create({
  rpcUrl: "https://rpc.testnet.miden.io",  // string URL or "testnet"/"devnet"/"localhost"/"local"
  noteTransportUrl: "https://transport.miden.io",
  storeName: "my-store",
  seed: "any string, or a Uint8Array",  // optional — see below
  proverUrl: "testnet",             // optional — sets a default prover
  autoSync: true,                   // optional — sync() once after init; ClientOptions default is false
  useWorker: true,                  // optional — default true; see below
  keystore: {                       // optional — external HSM/keystore
    getKey: async (pubKey) => { /* return secretKey or null */ },
    insertKey: async (pubKey, secretKey) => { /* persist */ },
    sign: async (pubKey, signingInputs) => { /* return signature */ },
  },
});
```

If `rpcUrl` is omitted, `create()` delegates to `createTestnet()`.

`seed?: string | Uint8Array`. A string is legal — `hashSeed()`
(`crates/web-client/js/utils.js`) SHA-256s it to 32 bytes before it reaches
WASM. A `Uint8Array` is passed through unchanged.

`autoSync` defaults to `false` in `ClientOptions`; `createTestnet` /
`createDevnet` inject `true`. `create()` only syncs `if (options?.autoSync)`.

### `useWorker`

`useWorker` defaults to `true` and runs WASM calls off the main thread. Leave
it on in browsers and extensions so the UI stays responsive. Set it to
`false` when:

- You pass a `CallbackProver` built with
  `TransactionProver.newCallbackProver(jsFn)`. The worker boundary serializes
  the prover with `TransactionProver.serialize()`, which has no encoding for
  the callback variant and silently downgrades it to `"local"` — the callback
  would never fire.
- You embed the client in a single-WebView native shell (Capacitor, Tauri,
  Electron preload), where the UI thread isn't competing with WASM anyway.

`client.lastAuthError()` (the raw JS value the last sign callback threw) is
also only meaningful with `useWorker: false`.

### Lazy / SSR-safe init

Some bundles (Next.js, Capacitor, raw `/lazy` entry) cannot await WASM at
import time. Use `MidenClient.ready()` to wait for WASM in-band — it is
idempotent and shared across callers:

```typescript
await MidenClient.ready();
const client = await MidenClient.createTestnet();
```

### Testing without a node

```typescript
const client = await MidenClient.createMock({ seed, serializedMockChain });
await client.proveBlock();                       // advance the mock chain one block
const dump = await client.serializeMockChain();  // snapshot/restore
client.usesMockChain();                          // boolean
```

### Termination

```typescript
client.terminate();   // terminates the underlying Web Worker
```

After `terminate()`, nearly every method throws (`assertNotTerminated`); the exceptions are `usesMockChain()`, the `defaultProver` getter, and `terminate()` itself. Guard against late callbacks on
unmount. `MidenClient` also implements `[Symbol.dispose]` /
`[Symbol.asyncDispose]`.

## Sync — Always Sync First

The client's view of the chain is only as fresh as its last sync. **Always
call `sync()` before reading account state or building a transaction that
depends on freshly received notes.**

```typescript
const summary = await client.sync();          // NTL fetch, then chain sync; fails fast on either
await client.syncChain();                     // on-chain state only, no NTL fetch
await client.syncNoteTransport();             // NTL fetch only
const height  = await client.getSyncHeight(); // current local block number
```

Common patterns:

- Sync before consuming notes (notes must be committed on-chain)
- Sync after submitting a transaction to observe the result
- Pass `waitForConfirmation: true` to a `transactions.send/mint/consume/swap`
  call to let the SDK wait for the tx commit instead of polling manually.
  `TransactionOptions` is `{ waitForConfirmation?, timeout?, prover? }` and
  `timeout` defaults to `60_000` ms of **wall clock**, not a block height.
- Use `client.waitForIdle()` to flush all queued WASM calls before doing a
  side-effect that must not race with a kernel callback (e.g. clearing an
  in-memory unlock token after a wallet "lock"). Caveat: a `syncState`
  blocked on the Web-Locks sync lock has not reached the internal call
  chain, so `waitForIdle` does not await it.

`autoSync: true` (injected by `createTestnet`/`createDevnet`) only triggers a
single sync at construction time — it is not a polling loop. Use the React
SDK's `useSyncState` or `MidenProvider` `autoSyncInterval` for periodic sync.

## Type Conversions

Type confusion across the WASM boundary is the leading source of bugs.

### `AccountId`

```typescript
const id = AccountId.fromHex("0xabc123...");          // throws on invalid hex
const id = Address.fromBech32("mtst1abc...").accountId();
const hex = id.toString(); // "0x..."
```

Pass `AccountId` (or any account ref the resource accepts: a hex/bech32
`string`, `Account`, `AccountHeader`, or `AccountId`) to resource methods —
never raw strings to methods that ask for `AccountId` directly. Note that an
`Address` object is **not** an account ref: `AccountRef = string | Account |
AccountHeader | AccountId`, and `resolveAccountRef` only special-cases
objects with an `.id()` method (`Address` exposes `accountId()`, not
`id()`), so call `address.accountId()` first.

The separate `resolveAddress` — used for the `to` field of
`notes.sendPrivate` / `notes.sendPrivateOutput` — does accept a bare
`AccountId` (it falls through to `Address.fromAccountId(ref, undefined)`),
but still not a pre-parsed `Address`.

`AccountId.fromHex` throws on malformed input; wrap in `try/catch` when
accepting user input.

### Amounts — Always `BigInt`

```typescript
BigInt(1000)
1000n           // numeric literal
BigInt("1000")
```

Amount fields accept `number | bigint` (`SendOptions`/`MintOptions.amount`,
`FaucetCreateOptions.maxSupply`) and are coerced internally with
`BigInt(...)`, so an integer `number` works and does **not** throw. The
hazard is pre-conversion precision loss: a numeric literal above
`Number.MAX_SAFE_INTEGER` (2^53) loses precision before it ever reaches
`BigInt()`. Use `bigint` for any value that might exceed 2^53.

A PSWAP `orderId` is stricter: it is `string | bigint` only, and a JS
`number` is **rejected** with a `TypeError`, because an order id is
`u64`-shaped and routinely exceeds `Number.MAX_SAFE_INTEGER`.

### Visibility & Account Types

```typescript
import { NoteVisibility, AccountType, AuthScheme, StorageMode, Linking }
  from "@miden-sdk/miden-sdk";

NoteVisibility.Public  // "public"
NoteVisibility.Private // "private"

// AccountType (package root) is a faucet-kind selector with ONLY two members:
AccountType.FungibleFaucet     // 0
AccountType.NonFungibleFaucet  // 1

AuthScheme.Falcon      // "falcon" — maps to AuthScheme.AuthRpoFalcon512
AuthScheme.ECDSA       // "ecdsa"  — maps to AuthScheme.AuthEcdsaK256Keccak

StorageMode.Public
StorageMode.Private

Linking.Dynamic        // "dynamic"
Linking.Static         // "static"
```

These are all `Object.freeze`d string/number consts in
`crates/web-client/js/index.js`.

Use `NoteVisibility` strings with the high-level resource APIs — `NoteType`
is a separate enum exported for the low-level WASM APIs and is easy to
confuse with `NoteVisibility`, so do not pass it where a `NoteVisibility` is
expected.

**Two different `AccountType`s exist.** The one exported at the package root
is the faucet-kind selector above. The low-level WASM `AccountType`
(`crates/web-client/src/models/account_type.rs`) is a different type whose
members are `{ Private, Public }` — account visibility. Do not mix them.

The root `AccountType` has no `MutableWallet`/`ImmutableWallet`/
`MutableContract`/`ImmutableContract` member — those evaluate to
`undefined`. Wallets and contracts are not chosen via `AccountType`: a
wallet is the default (omit `type`), and a contract is any
`accounts.create()` call that passes `components` (or `type:
"MutableContract"`/`"ImmutableContract"` as strings). See "Account Creation".

`StorageMode` has only `Public`/`Private`. There is no `StorageMode.Network`
(accessing it yields `undefined`, which silently resolves to private), and
the underlying `AccountStorageMode` rejects the string `"network"`.

## Account Creation

```typescript
// Wallet — the default when no `type` is given (storage "private", Falcon)
const wallet = await client.accounts.create();

// Wallet with explicit options — omit `type` (there is no
// AccountType.*Wallet member; passing one would be undefined → default wallet)
const wallet = await client.accounts.create({
  storage: "private",
  auth: AuthScheme.Falcon,
  seed: "optional string or Uint8Array",
});

// Faucet — selected via AccountType.FungibleFaucet / NonFungibleFaucet.
// Faucet default storage is "public".
const faucet = await client.accounts.create({
  type: AccountType.FungibleFaucet,
  storage: "public",
  name: "Dagger",              // optional human-readable name; defaults to `symbol`
  symbol: "DAG",
  decimals: 8,
  maxSupply: 10_000_000n,
});

// Custom contract — selected by passing `components` (NOT by an AccountType
// member). Requires a raw 32-byte seed and an AuthSecretKey.
// Contract default storage is "public".
const component = await client.compile.component({ code: contractMasm, slots: [] });
const contract = await client.accounts.create({
  seed: new Uint8Array(32),
  auth: secretKey,            // AuthSecretKey, not the AuthScheme enum
  components: [component],     // presence of `components` routes to a contract
});
```

A contract is whatever `accounts.create()` call carries `components` — the
string forms `type: "MutableContract"` / `"ImmutableContract"` also route to a
contract, but the canonical selector is `components`. There is **no**
`AccountType.MutableContract`; `type: AccountType.MutableContract` is
`undefined` and, without `components`, would silently create a wallet.

`components` must be **non-empty**. An auth-only contract is rejected:
`"Contract accounts require at least one non-auth procedure: pass at least
one entry in \`components\`."` Internally the contract path builds
`new AccountBuilder(seed).storageMode(mode)
  .withAuthComponent(AccountComponent.createAuthComponentFromSecretKey(auth))`,
then `.withComponent(c)` per entry, `.build()`, then
`newAccountWithSecretKey(account, auth)`.

## Transactions

The transactions API is option-bag-based and accepts any account ref
(`Account`, `AccountHeader`, hex string, `AccountId`).

### Send

`send` resolves to `{ txId, note, result }`. `note` is `null` unless
`returnNote: true`; `result` is a `TransactionResult`.

```typescript
const { txId, result } = await client.transactions.send({
  account: wallet,                 // sender
  to: "0xrecipient...",            // any account ref
  token: faucet,                   // faucet account ref — identifies the asset
  amount: 100n,
  type: NoteVisibility.Public,     // optional, but defaults to "public" — see note below
  reclaimAfter: 100,               // optional — sender can reclaim after this block
  timelockUntil: 50,               // optional — recipient can consume after this block
  waitForConfirmation: true,
  timeout: 30_000,
});
```

**`type` defaults to PUBLIC, not private** — for both `send` and `mint`, the
note-type resolver treats an omitted/`undefined` `type` as
`NoteVisibility.Public`. Omitting `type` therefore creates a **public** note (a
privacy hazard). Always pass `type: NoteVisibility.Private` explicitly when a
private note is required.

For private sends where you also need to deliver the note out-of-band, set
`returnNote: true` and the call narrows `note` to the constructed `Note`
object — incompatible with `reclaimAfter`/`timelockUntil` (explicit throw).

```typescript
const { txId, note } = await client.transactions.send({
  account: wallet,
  to: "mtst1...",                  // account ref: hex/bech32 string, Account,
                                   // AccountHeader, or AccountId (not an Address)
  token: faucet,
  amount: 100n,
  type: NoteVisibility.Private,
  returnNote: true,
});

// Stream the note via the note-transport service. Because this is one of
// this client's own output notes, use sendPrivateOutput — it derives the
// recipient's scan-start block from the note's stored expected height.
await client.notes.sendPrivateOutput({ noteId: note.id(), to: "mtst1..." });
```

### Mint

`mint` resolves to `{ txId, result }`.

```typescript
const { txId } = await client.transactions.mint({
  account: faucet,                 // faucet executes the mint
  to: targetAccountId,             // recipient
  amount: 1000n,
  type: NoteVisibility.Public,
  waitForConfirmation: true,
});
```

The transaction executes on the **faucet** — a frequent bug is passing the
recipient as `account`.

### Consume

```typescript
// Specific notes — `notes` takes a single NoteInput or an array of them
const { txId, result } = await client.transactions.consume({
  account: wallet,
  notes: [noteId1, noteRecord, "0xnote..."],   // any of: hex, NoteId, InputNoteRecord, Note
  waitForConfirmation: true,
});

// Drain everything consumable for the account
const { txId, consumed, remaining, result } = await client.transactions.consumeAll({
  account: wallet,
  maxNotes: 50,                    // optional cap
});
```

`ConsumeAllResult` is `{ txId: TransactionId | null, consumed: number,
remaining: number, result?: TransactionResult }` — `txId` is `null` and the
counts are `0` when there was nothing to consume.

### Swap

```typescript
await client.transactions.swap({
  account: wallet,
  offer: { token: tokenA, amount: 100n },    // field is `offer`, not `offered`
  request: { token: tokenB, amount: 50n },   // field is `request`, not `requested`
  type: NoteVisibility.Public,            // swap-note visibility
  paybackType: NoteVisibility.Private,    // payback-note visibility
});
```

> `paybackType` falls back to **`type`**, not to public: both `swap` and
> `pswapCreate` resolve it as `opts.paybackType ?? opts.type`. Omit it on a
> private swap and the payback note is private too. (The TypeScript JSDoc on
> these options says "Defaults to `public`" — that comment is wrong at this
> pin; the code is the contract.)

### Partial swaps (PSWAP)

A PSWAP note can be filled by many consumers; each fill emits a payback note
to the creator and, on a partial fill, a remainder PSWAP note carrying the
unfilled amount. The chain of notes is a *lineage*.

```typescript
await client.transactions.pswapCreate({
  account: wallet,
  offer: { token: tokenA, amount: 100n },
  request: { token: tokenB, amount: 50n },
  type: NoteVisibility.Public,
  paybackType: NoteVisibility.Public,   // defaults to `type`, NOT to public
});

await client.transactions.pswapConsume({
  account: filler,
  note: pswapNoteId,
  fillAmount: 10n,        // requested-asset amount supplied from the consumer's vault
  noteFillAmount: 0n,     // optional — supplied by other in-flight notes; leave unset normally
});

await client.transactions.pswapCancel({ account: wallet, note: pswapNoteId });
```

Lineage queries live on `client.pswap`:

```typescript
await client.pswap.lineages();                      // all tracked lineages
await client.pswap.lineagesFor(wallet);             // by creator account
await client.pswap.lineage(orderId);                // one lineage, or null
await client.pswap.cancelByOrder({ orderId });      // reclaims the tip; resolves the creator
```

`orderId` is `string | bigint` (never `number`). `PswapLineageRecord` exposes
`orderId()`, `creatorAccountId()`, `remainingOffered()`,
`remainingRequested()`, `currentDepth()`, `currentTipNoteId()` and `state()`
(`Active` / `FullyFilled` / `Reclaimed`). `cancelByOrder` throws before
submitting anything when no lineage is tracked or the lineage is terminal.
The read/build/submit steps are not atomic against external fills — if
another consumer advances the tip in between, the kernel rejects the cancel
with a "note already nullified" error; re-read the lineage and retry.

### Bridge

`bridge` emits a single public B2AGG (Bridge-to-AggLayer) note that the
bridge account consumes, burning the asset so it can be claimed at the
destination address. It resolves to `{ txId, result }`.

```typescript
await client.transactions.bridge({
  account: wallet,
  bridgeAccount: bridgeAccountId,
  token: faucet,
  amount: 100n,
  destinationNetwork: 1,                   // AggLayer-assigned network id
  destinationAddress: "0xabc...",          // 0x-prefixed Ethereum hex
});
```

### Network notes

`transactions.createNetworkNote(options)` returns `{ txId, note, result }`.
It builds a Public custom-script note carrying a `NetworkAccountTarget`
attachment, so a public network account auto-consumes it. Provide exactly one
of `recipient` or `script`. `Note.isNetworkNote()` reports the attachment.

The `target` must genuinely be a network account — one built from
`AccountComponent.createNetworkAuthComponents(allowedNoteScriptFees,
feeFaucetId, allowedTxScriptRoots?)`, which returns an `AccountComponent[]`
(install every element via `AccountBuilder.withComponent`) and both
allowlists **and prices** the note's script root. It must already be
committed on-chain at the transaction's reference block. Targeting a plain
wallet fails with `account procedure … is not in the account procedure index
map`.

### Execute (custom scripts)

```typescript
const script = await client.compile.txScript({
  code: scriptMasm,
  libraries: [{ namespace: "my::lib", code: libMasm, linking: "dynamic" }],
});

const { txId, result } = await client.transactions.execute({
  account: contract,
  script,
  foreignAccounts: [
    publicForeignAccountId,                          // storage requirements default to empty
    { id: otherPublicId, storage: storageRequirements },
  ],
  waitForConfirmation: true,
});
```

**Every foreign account here is a public one.** The web SDK exposes exactly one
constructor, `ForeignAccount.public(accountId, storageRequirements)`, and both
`execute` and `executeProgram` route every entry — bare id or `{ id, storage }`
wrapper — through it. There is no private foreign-account path on this surface,
and `ForeignAccount.public` rejects a non-public id with
`InvalidForeignAccountId`, so passing a private account's id throws rather than
falling back.

Storage requirements ride on the **public** account (that is what the `storage`
key is for); pass a bare id when the defaults suffice.

For a read-only view call, `transactions.executeProgram({ account, script,
adviceInputs?, foreignAccounts? })` returns a `FeltArray` of the resulting
stack. Nothing is proven or submitted.

### Preview — authorization summaries, NOT a dry run

`transactions.preview({ operation, ... })` accepts
`"send" | "mint" | "bridge" | "consume" | "swap" | "pswapCreate" |
"pswapConsume" | "pswapCancel" | "custom"`.

It returns a `TransactionSummary` **only while authorization is pending** —
that is, when the account's auth procedure aborts with the unauthorized
event (e.g. a multisig below its signing threshold). That summary is the
payload out-of-band signing flows need.

If the transaction is already fully authorized, execution succeeds, **no
summary is produced**, and the call **rejects** with an error whose `code`
is `"TRANSACTION_ALREADY_AUTHORIZED"` (on Node.js the code prefixes the
message instead). Submit it with `execute`/`submit` instead. Do not use
`preview` to power a confirmation screen or estimate a transaction.

`anchor` is accepted **only** with `operation: "custom"`; passing it with a
built-in operation throws `preview does not accept an anchor for operation
"…"`.

### Chain anchors

A signed `TransactionSummary` binds the reference block commitment, so a
summary signed at one block only reproduces when re-executed at that block.
`ChainAnchor` is what lets a multisig proposer, its co-signers, and the
eventual executor agree despite different sync heights.

```typescript
const anchor  = await client.transactions.captureAnchor(request);
const summary = await client.transactions.preview({
  operation: "custom", account, request, anchor,
});
// ... collect signatures over `summary`, shipping `anchor.serialize()` ...
await client.transactions.submit(account, request, { anchor });
```

- `captureAnchor(request)` pins the current sync height for that specific
  request, tracking the creation blocks of its authenticated input notes.
- Verify an untrusted anchor with `anchor.commitment()` against
  `summary.blockCommitment()`.
- It throws with `code: "INVALID_CHAIN_ANCHOR"` if a sync lands mid-capture;
  retry.
- The caller owns the anchor and it carries a partial blockchain — call
  `anchor.free()` in a repeated-capture flow rather than waiting for the
  finalizer.
- `ChainAnchor` also has `serialize()` / `deserialize()` / `blockNum()` /
  `blockHeader()`.
- Only the request-taking methods accept an anchor: `preview({operation:
  "custom"})`, `executeRequest`, and `submit`. Passing `anchor` to `send`,
  `execute`, `batch`, `submitBatch` etc. throws loudly rather than silently
  executing at the tip.

### Manual transaction lifecycle

```typescript
const executed  = await client.transactions.executeRequest(account, request, { anchor });
const proven    = await executed.prove({ prover });
const submitted = await proven.submit();
await submitted.apply();
```

- `executeRequest` returns a `TransactionExecution` (`.result`, `.id`,
  `.prove({ prover? })`)
- `.prove()` returns a `TransactionProof` (`.proof`, `.result`, `.submit()`)
- `.submit()` returns a `TransactionSubmission` (`.blockNumber`, `.result`,
  `.apply()`, `.waitForConfirmation(opts)`)
- `transactions.submit(account, request, options?)` runs every stage in one
  call and returns `{ txId, result }`
- `submitProven(proof, result)` submits a proof produced by a detached prover
  that never saw the local store, returning a `TransactionSubmission`

**The stages are not atomic as a group.** Awaiting other mutating calls on
the same account between them can interleave state — drive the chain as an
uninterrupted sequence per account. A prover is **consumed** by `prove()`;
build or clone a fresh one per call, or it silently falls back to the
built-in local prover.

### Batching

```typescript
// Every operation executes AS `account`. Pick operations one account can perform.
const { blockNumber } = await client.transactions.batch({
  account: wallet,
  operations: [
    { kind: "consume", notes: [noteId] },
    { kind: "send", to: other, token: faucet, amount: 10n },
    { kind: "custom", request: prebuiltRequest },
  ],
  waitForConfirmation: true,
});
```

`BatchOperation` kinds are `send`, `mint`, `consume`, `swap`, `execute`,
`custom`; each mirrors the singular options minus `account`.

**V1 is single-account only, and it rewrites every operation's account.** The
builder does `{ ...op, account: opts.account }` for each operation — its own
comment reads "Per-op builders all use the batch-level `account` — V1 only
supports same-account batches". Mixing account roles in one batch therefore
does not produce a helpful error; it builds the wrong request:

```typescript
// WRONG — a mint must execute on the FAUCET, but the batch rebuilds it as
// `wallet`, i.e. it treats the wallet as the issuing faucet. Setting
// `account` to the faucet instead just breaks the wallet send.
await client.transactions.batch({
  account: wallet,
  operations: [
    { kind: "mint", to: wallet, amount: 100n },
    { kind: "send", to: other, token: faucet, amount: 10n },
  ],
});
```

Minting on a faucet and spending from a wallet are two different accounts, so
they are two calls — two batches, or a `mint` followed by a `send`.

The result is only `{ blockNumber }`, so `waitForConfirmation` polls chain
height rather than per-transaction status. `submitBatch(account, requests[], options?)`
is the pre-built-request counterpart; the V1 batch API has no per-call prover
override.

### Listing and waiting

```typescript
await client.transactions.list();                          // all
await client.transactions.list({ status: "uncommitted" });
await client.transactions.list({ ids: [txId] });
await client.transactions.list({ expiredBefore: 1000 });

await client.transactions.waitFor(txId, {
  timeout: 60_000,   // default; 0 polls indefinitely
  interval: 5_000,   // default
  onProgress: (status) => {},   // "pending" | "submitted" | "committed"
});
```

`TransactionRecord` exposes `id()`, `accountId()`, `blockNum()`,
`submissionHeight()`, `expirationBlockNum()`, `creationTimestamp()`,
`transactionStatus()`, `initAccountState()`, `finalAccountState()`,
`inputNoteNullifiers()` and `outputNotes()`.

## Notes

```typescript
await client.notes.list();                             // all input notes
await client.notes.list({ status: "committed" });      // "consumed" | "committed" |
                                                       // "expected" | "processing" | "unverified"
await client.notes.list({ ids: [noteId] });
await client.notes.list({ scriptRoots: [noteScript.root()] });  // hex strings or Word
await client.notes.get(noteId);                        // single record, or null
await client.notes.listSent();                         // output notes
await client.notes.listAvailable({ account: wallet }); // consumable for an account

// Import/export
const idHex = await client.notes.import(noteFile);     // hex string, NOT a NoteId
const file  = await client.notes.export(noteId);
```

`NoteQuery` is a discriminated union — `{status}`, `{ids}`, or
`{scriptRoots}`. `listSent` returns `[]` for a `scriptRoots` query, since
script roots are only tracked for received notes.

`notes.import` returns a **hex string**: the note id when the file carries
metadata, or the note's *details commitment* for a details-only file. Pass it
to `NoteId.fromHex` if you need a `NoteId` object.

### Private-note transport

```typescript
// Pulls anything addressed to tracked accounts, incrementally from the
// stored pagination cursor.
await client.notes.fetchPrivate();

// One of THIS client's own output notes — preferred. The recipient's
// scan-start block is derived from the note's stored expected height.
await client.notes.sendPrivateOutput({ noteId, to: "mtst1..." });

// Any other note — you must supply the scan hint yourself.
await client.notes.sendPrivate({
  note,
  to: "mtst1...",
  scanAfterBlockNum: heightWhenSubmitted,
});
```

`fetchPrivate()` takes no arguments and only downloads notes past the stored
cursor. Historical notes for a newly tracked tag sit below that cursor and
are backfilled automatically by `sync()`, one tag at a time.

`sendPrivate` **requires** `scanAfterBlockNum: number` — the block the
recipient scans *forward* from for the note's on-chain commitment. It must be
at or below the commitment block; a hint above it is never scanned back to,
so the recipient silently never receives the note. A safe choice is the chain
tip at the moment the note's transaction was submitted. A missing or negative
value throws a descriptive `Error`.

For one of this client's own output notes, do not compute the hint yourself
and do not pass the current sync height — use `sendPrivateOutput({ noteId,
to })`, which derives it from the note's stored `expected_height`. A bare
sync-height hint overshoots the commitment once the sender advances past it
(e.g. relaying after waiting for commit) and silently drops delivery.

For both, `to` accepts a bech32 string, a 0x-hex string, an `Account`, or an
`AccountId` (resolved via `resolveAddress`). It does **not** accept a
pre-parsed `Address` object.

## Accounts (querying)

```typescript
await client.accounts.list();                         // tracked accounts (AccountHeader[])
await client.accounts.get(ref);                       // single (returns null if not tracked)
await client.accounts.getOrImport(ref);               // tries get(), falls back to import()
await client.accounts.getDetails(ref);                // { account, vault, storage, code, keys }
await client.accounts.insert({ account, overwrite }); // start tracking an existing account
await client.accounts.getBalance(account, token);     // single-asset balance, returns bigint

await client.accounts.import(ref);                    // by id — fetches state from the network
await client.accounts.import({ file });               // from an exported AccountFile
await client.accounts.import({ seed, auth });         // reconstruct a PUBLIC account from its seed
const file = await client.accounts.export(ref);       // AccountFile

await client.accounts.addAddress(ref, "mtst1...");
await client.accounts.removeAddress(ref, "mtst1...");
```

`getDetails(ref)` returns `{ account, vault, storage, code, keys }` — the full
`Account`, its `AssetVault`, `AccountStorage`, `AccountCode | null`, and the key
commitments (`Word[]`); there is no `status` field.

The seed-based import path only works for **public** accounts; use the
account-file workflow for private ones.

For a single asset balance without loading the full vault, prefer
`client.accounts.getBalance(account, token)` (returns `bigint`). It wraps the
underlying WASM client's `accountReader(id)` lazy reader, which you can
drop into directly for finer-grained reads.

## Storage — slots are named, not indexed

`StorageSlot` constructors take a slot **name**:

```typescript
StorageSlot.fromValue(name, word);
StorageSlot.emptyValue(name);
StorageSlot.map(name, storageMap);
```

MASM declares the matching name as a word constant and reads through it:

```
const COUNTER_SLOT = word("miden::tutorials::counter")
...
push.COUNTER_SLOT[0..2] exec.active_account::get_item
```

Read state back through `StorageView`, installed on `Account.prototype.storage()`
at WASM load time: `getItem(slotName)`, `getMapItem(slotName, key)`,
`getMapEntries(slotName)`, `getCommitment(slotName)`, `getSlotNames()`.
`getItem` returns a `StorageResult` supporting `.isMap`, `.entries`, `.word`,
`.toFelts()`, `.toU64s()`, `.toBigInt()`, `.toHex()` and `.valueOf()`. Use
`.toBigInt()` for exact u64 values — `valueOf()` throws `RangeError` above
`Number.MAX_SAFE_INTEGER`.

## Keystore

```typescript
await client.keystore.insert(accountId, secretKey);
await client.keystore.get(pubKeyCommitment);
await client.keystore.remove(pubKeyCommitment);
await client.keystore.getCommitments(accountId);
await client.keystore.getAccountId(pubKeyCommitment);
```

`keystore.insert` is the single call that both stores the key and registers
its commitment with the account. These five are the entire resource. Note that `remove()` is Node-only: on the browser/WASM path it unconditionally throws `"remove() is not supported on this platform"`.

## Compile

```typescript
await client.compile.component({ code, namespace, slots, supportAllTypes: true });
await client.compile.txScript({ code, libraries });
await client.compile.noteScript({ code, libraries });
```

`compile.component` takes an optional `namespace?: string` — the module path
used to derive procedure identities, routed to
`compileAccountComponentCodeWithPath(namespace, code)`. Use the **same**
namespace when linking that component into a transaction script, or procedure
identities will not match. `slots` defaults to `[]` and `supportAllTypes`
defaults to `true`.

`libraries` entries can be any of three shapes (`CompileScriptLibrary`):

```typescript
{ namespace: "my::lib", code: libMasm, linking: "dynamic" }  // inline source
{ component: myAccountComponent, linking: "dynamic" }        // the exact installed code
prebuiltLibrary                                              // a Library object
```

Prefer the `{ component }` form when the script calls into a component you
installed on the account — it links the exact compiled code, so procedure
identities match. Linking defaults to dynamic.

### MASM annotations are mandatory

Anything compiled through `client.compile` must carry its annotation, or
compilation fails:

- account-component procedures: `@account_procedure`
- transaction scripts: `@transaction_script` on `pub proc main`
- note scripts: `@note_script` on `pub proc main`

Note scripts are **MASM libraries with a single `@note_script`-annotated
procedure**, not begin/end programs — `client.compile.noteScript` builds the
correct shape from a procedure body.

## Web SDK surface boundaries

Guards against bad find-replaces and misremembered APIs:

- There is no JS/TS `AssetId`, `AssetClass` or `AssetVaultKey` type. Every
  `assetId`-named field in the React SDK is a faucet account id string.
- Fee-aware custom requests start from the public client instance method
  `await client.feeAwareTransactionRequestBuilder(executingAccount)`. The
  client supplies native-asset 1:1 conversion information, and the returned
  builder already carries a salt when the auth scheme requires one. Use
  `withFeeConversionSalt` only to set a pre-agreed salt on a bare builder or
  replace the generated value intentionally. This is separate from network-account note pricing (`NoteScriptFee`,
  `AccountComponent.createNetworkAuthComponents`, `NoteScript.feeSponsorship()`).
- A note may carry at most **16** assets (`MAX_ASSETS_PER_NOTE` in the
  protocol). It is enforced in `NoteAssets::new`, so it surfaces as a runtime
  `NoteError`, not a type error.
- `ClientOptions` has no `debugMode`, and the low-level
  `createClient(rpcUrl?, noteTransportUrl?, seed?, storeName?, logLevel?,
  useWorker?)` / `createClientWithExternalKeystore(rpcUrl?,
  noteTransportUrl?, seed?, storeName?, getKeyCb?, insertKeyCb?, signCb?,
  logLevel?, useWorker?)` take no trailing debug flag.
- `ExecutedTransaction` and `TransactionStoreUpdate` expose `accountPatch()`,
  not `accountDelta()`. (`TransactionSummary.accountDelta()` deliberately
  still exists and still returns an `AccountDelta`.)
- `TransactionSummary` exposes `userParams()` (seven field elements), not
  `salt()`.
- `notes.fetchPrivate` takes no arguments — there is no `{ mode: "all" }`.
- `FungibleAsset` has no `withCallbacks(flag)`; the flag is an immutable
  property of the faucet's account id and is read with `callbacks()`.
- Note scripts call `basic_wallet::move_note_assets_to_account`, not
  `add_assets_to_account`.

## Common Workflows

### Mint and consume (fund a fresh wallet)

```typescript
const wallet = await client.accounts.create();
const faucet = await client.accounts.create({
  type: AccountType.FungibleFaucet,
  storage: "public",
  symbol: "TEST",
  decimals: 8,
  maxSupply: 1_000_000n,
});

await client.transactions.mint({
  account: faucet,
  to: wallet,
  amount: 10_000n,
  type: NoteVisibility.Public,
  waitForConfirmation: true,
});

await client.sync();
await client.transactions.consumeAll({
  account: wallet,
  waitForConfirmation: true,
});
```

### Wait for an external transfer

```typescript
await client.sync();
const before = (await client.notes.listAvailable({ account: wallet })).length;

while (true) {
  await new Promise(r => setTimeout(r, 3000));
  await client.sync();
  const now = (await client.notes.listAvailable({ account: wallet })).length;
  if (now > before) break;
}
```

## Common Pitfalls

1. **Forgetting to sync.** Notes won't appear, balances will be stale, foreign
   accounts will be at the wrong block.
2. **`number` literals above 2^53 for amounts.** Amount fields accept
   `number | bigint` and coerce via `BigInt()` (no `TypeError`), but a numeric
   literal above `Number.MAX_SAFE_INTEGER` loses precision *before* coercion.
   Use `bigint` for large amounts — and always for a PSWAP `orderId`, which
   rejects `number` outright.
3. **Omitting `type` and expecting a private note.** `send`/`mint` default
   `type` to **public** — pass `NoteVisibility.Private` explicitly for privacy.
4. **Passing a low-level `AccountId`-only WASM method a raw string** — resource
   methods accept hex/bech32 strings, but pre-parse with `AccountId.fromHex()`
   (and catch its throw) when calling APIs that demand an `AccountId` directly.
5. **Consuming notes before they're committed** — sync first, check status.
6. **Submitting `mint` with the recipient as `account`** — mint executes on
   the faucet account, not the target.
7. **Private notes without transport.** A private note still has to be
   relayed. For your own output note call
   `notes.sendPrivateOutput({ noteId, to })`. For any other note call
   `notes.sendPrivate({ note, to, scanAfterBlockNum })` and pass a block at or
   below the note's commitment block — `sendPrivate` throws without it, and a
   too-high hint silently loses the note.
8. **Treating `preview` as a dry run.** On a fully-authorized transaction it
   rejects with `code: "TRANSACTION_ALREADY_AUTHORIZED"`. It only yields a
   summary while authorization is pending.
9. **Destructuring the wrong result shape.** `send` gives
   `{ txId, note, result }`; `mint`/`consume`/`swap`/`execute`/`bridge`/
   `pswap*` give `{ txId, result }`; `consumeAll` gives
   `{ txId, consumed, remaining, result? }`; `batch`/`submitBatch` give
   `{ blockNumber }`.
10. **Holding WASM-owned objects across `terminate()`** — every `Account`,
    `Note`, `AccountId`, `NoteAndArgsArray` etc. owns Rust memory through the
    WASM ArrayBuffer. After `terminate()` they panic with "null pointer
    passed to rust" — drop references on unmount.
11. **Calling `accountReader(...)` in parallel with a write** — the readers
    share the WASM client. Wrap concurrent flows with `client.waitForIdle()`
    or rely on the React SDK's `runExclusive`.
12. **Reusing a `TransactionProver` across `prove()` calls** — it is consumed,
    and the second call silently falls back to the built-in local prover.
