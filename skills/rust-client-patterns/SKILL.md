---
name: rust-client-patterns
description: Enforce coding conventions for the miden-client Rust codebase (rust-client, sqlite-store). Use when editing, reviewing, or creating Rust code in the miden-client workspace — covers error handling, Store trait methods, the Client<AUTH> generic, the Keystore super-trait that constrains the ClientBuilder, builder constructors, lazy reader patterns, and `no_std` organization.
---

# Miden Client Rust Patterns

The crate ships under `crates/rust-client`, with `crates/sqlite-store` as the
native persistence backend. Reusable **test utilities** live in
`crates/rust-client/src/test_utils`, re-exported as `miden_client::testing`
behind the `testing` feature; `crates/testing/` holds the test crates
themselves (`miden-client-tests`, `test-node-genesis`), not utilities to depend
on. The WASM/IndexedDB store and the JS web client live in the separate
`0xMiden/web-sdk` repository.

The upstream repository is `https://github.com/0xMiden/rust-sdk`; the crate is
still published as `miden-client`. The MSRV tracks `rust-toolchain.toml`
there — copy that channel into the consumer's toolchain file rather than
hard-coding a number that drifts.

Pin the exact pre-release strings; Cargo does not match a pre-release against a
plain `"0.16"` requirement:

```toml
miden-client              = "0.16.0-rc.5"
miden-client-sqlite-store = "0.16.0-rc.5"
miden-protocol            = "0.16.0-rc.9"
miden-standards           = "0.16.0-rc.9"
miden-tx                  = "0.16.0-rc.9"
miden-tx-batch            = "0.16.0-rc.9"
miden-assembly            = "0.29.1"
miden-core                = "0.29.1"
miden-processor           = "0.29.1"
miden-prover              = "0.29.1"
miden-crypto              = "0.29.1"
```

## Section Headers

Organize code with section comment headers. Two levels:

**Top-level sections** (96 `=` characters):
```rust
// SECTION NAME
// ================================================================================================
```

**Subsections within impl blocks or traits** (92 `-` characters):
```rust
    // SUBSECTION NAME
    // --------------------------------------------------------------------------------------------
```

Use ALL-CAPS with spaces between words. Apply consistently to organize:
- Module-level sections: `RE-EXPORTS`, `MIDEN CLIENT`, `CLIENT RNG`, `CONSTANTS`
- Trait definitions by domain: `TRANSACTIONS`, `NOTES`, `CHAIN DATA`, `ACCOUNT`, `SYNC`
- Impl block method groupings: `ACCOUNT CREATION`, `ACCOUNT DATA RETRIEVAL`

(These are illustrative of the style; match the section name to the code's
domain rather than copying these verbatim.)

## Error Handling

### Primary Error Enum

Use `thiserror` with `#[derive(Debug, Error)]`:

```rust
#[derive(Debug, Error)]
pub enum ClientError {
    #[error("account with id {0} is already being tracked")]
    AccountAlreadyTracked(AccountId),

    #[error("account error")]
    AccountError(#[from] AccountError),

    #[error("storage error")]
    StoreError(#[from] StoreError),

    #[error("transaction script error")]
    TransactionScriptError(#[source] TransactionScriptError),
}
```

Rules:
- Each variant has `#[error("...")]` with a clear, specific message
- Use `#[from]` for automatic conversion from nested error types (this is the
  common case in `ClientError`, e.g. `AccountError`, `StoreError`,
  `RpcError`, `NoteScreenerError`)
- Use `#[source]` when you want source chaining but *not* an auto-`From`
  (e.g. `TransactionInputError`, `TransactionScriptError`, or struct variants
  with a named `#[source] source` field)
- Include context data (IDs, values) in the error message itself

### ErrorHint for User Guidance

Implement `From<&YourError> for Option<ErrorHint>` to provide actionable help.
Match the variants that have hints and fall back to `None`:

```rust
impl From<&ClientError> for Option<ErrorHint> {
    fn from(err: &ClientError) -> Self {
        match err {
            ClientError::MissingOutputRecipients(recipients) => {
                Some(missing_recipient_hint(recipients))
            },
            _ => None,
        }
    }
}
```

### Error Propagation

Wrap lower-level errors explicitly with `.map_err()`:

```rust
self.store
    .get_addresses_by_account_id(self.account_id)
    .await
    .map_err(ClientError::StoreError)
```

`.map_err(ClientError::StoreError)` is the canonical way to surface a
`StoreError` from a `Store` call inside the client.

Prefer propagating with `?` after mapping over `.unwrap()`. `.expect()` does appear in the crate for invariants the author has already proven (e.g. `"Default executor's options should always be valid"`), so treat it as reserved for that case and carrying a message that states the invariant — not as a shortcut around a fallible call.

## Store Trait

### Cross-Platform Async Trait

The Store trait must work on both native and WASM. Always use this dual cfg_attr:

```rust
#[cfg_attr(not(target_arch = "wasm32"), async_trait::async_trait)]
#[cfg_attr(target_arch = "wasm32", async_trait::async_trait(?Send))]
pub trait Store: Send + Sync {
    // ...
}
```

The WASM variant uses `?Send` because WASM is single-threaded.

### Adding a New Store Method

1. Add the method signature to the `Store` trait in `crates/rust-client/src/store/mod.rs`, in the appropriate section
2. Implement it in `SqliteStore` (`crates/sqlite-store/src/lib.rs`) — delegate to a connection method
3. Add to the `StoreError` enum if new error conditions are needed

The native backend in this workspace is `SqliteStore`. The WASM/IndexedDB
`Store` implementation lives in the separate `0xMiden/web-sdk` repo; if a new
method must also exist there, mirror it in that repo.

SqliteStore delegation pattern:
```rust
async fn get_note_tags(&self) -> Result<Vec<NoteTagRecord>, StoreError> {
    self.interact_with_connection(SqliteStore::get_note_tags).await
}

async fn add_note_tag(&self, tag: NoteTagRecord) -> Result<bool, StoreError> {
    self.interact_with_connection(move |conn| SqliteStore::add_note_tag(conn, tag))
        .await
}
```

`interact_with_connection` acquires a pooled connection and runs the provided
closure, returning its `Result`.

### Trait Method Documentation

Every trait method needs a rustdoc comment explaining what it does:

```rust
/// Retrieves stored transactions, filtered by [`TransactionFilter`].
async fn get_transactions(
    &self,
    filter: TransactionFilter,
) -> Result<Vec<TransactionRecord>, StoreError>;
```

### Interior Mutability

All trait methods use `&self`, not `&mut self`. Implementations must use interior mutability (e.g., `Mutex`, `RwLock`, or browser-native locks), because the store's ownership is shared between the executor and the client.

All update operations must be atomic — if an error occurs partway through, roll back all changes.

## Client\<AUTH\> Pattern

### Struct Definition

The client is generic over the authenticator:

```rust
pub struct Client<AUTH> {
    store: Arc<dyn Store>,
    rng: ClientRng,
    rpc_api: Arc<dyn NodeRpcClient>,
    tx_prover: Arc<dyn TransactionProver + Send + Sync>,
    authenticator: Option<Arc<AUTH>>,
    // ...
}
```

Rules:
- Use `Arc<dyn Trait>` for polymorphic dependencies
- Use `Option<Arc<AUTH>>` for the optional authenticator
- Document each field with `///` comments

### Impl Block Constraints

Apply the AUTH constraint per impl block, not on the struct. The
`Client<AUTH>` impl blocks use these bounds:

```rust
// Constructors: `Client::builder()` requires the builder's authenticator bound.
impl<AUTH> Client<AUTH>
where
    AUTH: builder::BuilderAuthenticator,
{
    pub fn builder() -> builder::ClientBuilder<AUTH> { ... }
}

// Access / signing methods need at least TransactionAuthenticator.
impl<AUTH> Client<AUTH>
where
    AUTH: TransactionAuthenticator,
{
    pub fn authenticator(&self) -> Option<&Arc<AUTH>> { ... }
    // code_builder, note_screener, rng, prover, source_manager
}

// Methods that don't touch AUTH at all use an unconstrained block.
impl<AUTH> Client<AUTH> {
    pub fn store_identifier(&self) -> &str { ... }
    pub fn with_transaction_observer(&mut self, observer: Arc<dyn TransactionObserver>) { ... }
    pub async fn network_id(&self) -> Result<NetworkId, ClientError> { ... }
}
```

**There is no debug toggle.** `DebugMode`, `ClientBuilder::in_debug_mode`,
`Client::in_debug_mode`, the CLI `--debug` flag and the `MIDEN_DEBUG`
environment variable do not exist. There is nothing to gate: MASM print-style
debugging goes through the `miden::core::debug` procedures, which print
unconditionally.

What replaced them is a debug adapter, not a flag. The client carries an
optional `dap` feature (`dap = ["dep:miden-debug", "dep:miden-processor", "std"]`)
backing a `DapProgramExecutor`. The CLI has its **own** `dap` feature
(`dap = ["dep:miden-debug", "miden-client/dap"]`) which is **not** in its
`default = []`, so a stock CLI build exposes nothing — enabling the library
feature alone is not enough. When the CLI is built with its `dap` feature, the
flags `--start-debug-adapter <ADDR>` and `--record <FILE>` appear on exactly two
commands: `exec` and `consume-notes`. `mint`, `transfer`, `swap` and the PSWAP
commands do not accept them.

(The sync methods sit in their own block bounded by
`AUTH: TransactionAuthenticator + Sync + 'static`.)

There is **no** `impl<AUTH> Client<AUTH> where AUTH: Keystore` block, and
`Client` exposes no key-management methods (no `add_key`/`remove_key`/`get_key`).
Key management is performed directly on the keystore object (see below), not
through `Client`. The only key-related accessor on `Client` is
`authenticator()`, which returns the stored `Option<&Arc<AUTH>>`.

### `Keystore` super-trait

`Keystore` (in `miden_client::keystore`) extends `TransactionAuthenticator`
and adds the unified key-management surface:

```rust
#[cfg_attr(not(target_arch = "wasm32"), async_trait::async_trait)]
#[cfg_attr(target_arch = "wasm32", async_trait::async_trait(?Send))]
pub trait Keystore: TransactionAuthenticator {
    async fn add_key(&self, key: &AuthSecretKey, account_id: AccountId) -> Result<(), KeyStoreError>;
    async fn remove_key(&self, pub_key: PublicKeyCommitment) -> Result<(), KeyStoreError>;
    async fn get_key(&self, pub_key: PublicKeyCommitment) -> Result<Option<AuthSecretKey>, KeyStoreError>;
    async fn get_account_key_commitments(&self, account_id: &AccountId)
        -> Result<BTreeSet<PublicKeyCommitment>, KeyStoreError>;
    async fn get_account_id_by_key_commitment(&self, pub_key_commitment: PublicKeyCommitment)
        -> Result<Option<AccountId>, KeyStoreError>;
    async fn get_keys_for_account(&self, account_id: &AccountId)
        -> Result<Vec<AuthSecretKey>, KeyStoreError> { ... } // default impl
}
```

A single `keystore.add_key(&secret, account_id)` call both stores the key
and associates it with the given account — there is no separate "insert key" +
"register commitment" step. In this workspace `FilesystemKeyStore` (behind the
`std` feature) is the only `Keystore` impl re-exported from
`crates/rust-client/src/keystore`; the WASM keystore lives in the
`web-sdk` repo.

The `Keystore` bound reaches the client via the builder: the `ClientBuilder`
is constrained by `BuilderAuthenticator`, a marker super-trait defined as
`Keystore + 'static` (and additionally `From<FilesystemKeyStore>` under the
`std` feature).

### Builder Pattern

Use `ClientBuilder<AUTH>` with `Default` impl and detailed doc comments on each field:

```rust
pub struct ClientBuilder<AUTH> {
    /// An optional custom RPC client. If provided, this takes precedence over `rpc_endpoint`.
    rpc_api: Option<Arc<dyn NodeRpcClient>>,
    /// An optional store provided by the user.
    pub store: Option<StoreBuilder>,
    // ...
}
```

The `store` field holds a `StoreBuilder` (either an already-built
`Arc<dyn Store>` via `StoreBuilder::Store`, or a deferred `StoreFactory` via
`StoreBuilder::Factory`); the `.store(...)` method takes an `Arc<dyn Store>`
and wraps it into `StoreBuilder::Store`.

Provide network-specific constructors: `for_testnet()`, `for_devnet()`,
`for_localhost()`. Each returns `Self` synchronously and pre-fills the RPC
endpoint for that network. `for_testnet()` and `for_devnet()` additionally
pre-fill a remote prover and the note-transport endpoint; `for_localhost()`
sets *only* the RPC endpoint (leaving the prover to fall back to the default
local prover at `build()` time, and configuring no note transport). The RNG is
*not* network-specific and is *not* set by any of these constructors — it is
left unset (`Default` leaves `rng: None`) and resolved at `build()` time, where
a user-supplied RNG is used if present, otherwise a seed-based `ClientRng` is
created from `rand::rng()`. The default prover, when unset, resolves to a
`LocalTransactionProver` at `build()`. Only `build()` is async (it constructs
the client from the configured components):

```rust
let client = ClientBuilder::for_testnet()
    .store(store)                        // Arc<dyn Store>
    .authenticator(Arc::new(keystore))   // accepts any AUTH: BuilderAuthenticator (i.e. Keystore + 'static)
    .build()
    .await?;
```

`build()` returns `ClientInitializationError` if no RPC client or no store was
configured. Builder defaults worth knowing: `TX_DISCARD_DELTA = 20`,
`IRRELEVANT_BLOCK_PRUNE_INTERVAL = 1`, `CACHE_PARTIAL_MMR_IN_MEMORY = false`.

Other builder methods: `grpc_client(&Endpoint, Option<u64>)`, `source_manager`,
`irrelevant_block_prune_interval(Option<u32>)`,
`cache_partial_mmr_in_memory(bool)`, `tx_graceful_blocks(Option<u32>)`,
`note_transport(Arc<dyn NoteTransportClient>)`, `endpoint() -> Option<&Endpoint>`,
and — on `ClientBuilder<FilesystemKeyStore>` — `filesystem_keystore(path)`.

#### `.rpc()` does not verify responses

`ClientBuilder::rpc()` takes the client **as provided**. Only `grpc_client(..)`
and the `for_testnet` / `for_devnet` / `for_localhost` constructors wrap the
transport in `VerifyingRpcClient`. Handing `.rpc()` a bare `GrpcClient`
compiles, runs, and silently drops response verification:

```rust
// Wrong: no response verification, and nothing tells you so.
ClientBuilder::new().rpc(Arc::new(GrpcClient::new(&endpoint, timeout)))

// Right: wrap it, or use grpc_client()/for_*() which wrap for you.
ClientBuilder::new().rpc(Arc::new(VerifyingRpcClient::new(GrpcClient::new(&endpoint, timeout))))
ClientBuilder::new().grpc_client(&endpoint, Some(timeout))
```

### Account updates: `AccountPatch`, and the `account_delta` exception

An executed transaction reports the account's new state as an **`AccountPatch`**:
`TransactionResult::account_patch() -> &AccountPatch`.

`AccountDelta` has not gone away and is not a stale alias. It is *relative* —
it records how much things changed — and it is what a transaction summary
commits to. `TransactionSummary::account_delta() -> &AccountDelta` is
deliberately still a delta. Renaming that call site to `account_patch()`, or
rewriting the code around it to expect absolute values, is a semantic bug that
the compiler will not catch on the summary path.

### Fees

```rust
let request = TransactionRequestBuilder::new()
    .fee_conversion_salt(salt)
    .build()?;
```

`fee_conversion_salt` declares the salt; during transaction preparation the client creates the
native-asset 1:1 fee-conversion information. It and `auth_arg()` are mutually exclusive: setting
one clears the other. Leave the salt unset for the supported single-signature default. The
multisig, smart-multisig, and guarded-multisig auth variants require a caller-chosen salt; auth
components that do not support fee conversion reject an explicitly declared salt.

### `AssetId` is the vault key, not the asset class

`miden_client::asset` re-exports `AssetId` as the vault's unique identifier for
an asset; the per-faucet class within an asset id is a separate type,
`AssetClass`. The names are a trap: code that treats `AssetId` as the asset
class compiles and is wrong. `miden_client::asset` also exposes `AssetAmount`,
`AssetCallbacks`, `AssetComposition`, `AssetWitness`, and `PartialVault`.

## Lazy Reader Patterns

Prefer the lazy readers over loading whole `Account` / `Note` records when
all you need is one field — they avoid materializing storage maps and
asset vaults that a frontend will not display anyway.

```rust
// Account fields without loading the full Account
let reader = client.account_reader(account_id);
let (header, status) = reader.header().await?;
let balance        = reader.get_balance(faucet_id).await?;        // AssetAmount, not u64; AssetAmount::ZERO when absent
let storage_item   = reader.get_storage_item(slot_name).await?;  // slot_name: impl Into<StorageSlotName>
let nonce          = reader.nonce().await?;
let vault_root     = reader.vault_root().await?;
let storage_root   = reader.storage_commitment().await?;
let code_root      = reader.code_commitment().await?;

// Iterator over consumed input notes (NoteFilter::Consumed; on-chain consumption order)
let mut notes = client.input_note_reader(consumer_account_id);
while let Some(note) = notes.next().await? {
    // process each InputNoteRecord
}
```

Both readers borrow `&self` and may be invoked concurrently with one another.
They must not be used concurrently with a `Client` write that targets the
same account, so wrap mixed flows in a serializing layer. (The JS wrapper that
serializes WASM calls for browser consumers lives in the `web-sdk` repo.)

## State Sync

`Client::sync_state()` takes no arguments (it borrows `&mut self`). Internally
it runs note-transport sync (`sync_note_transport()`) and then `sync_chain()`;
`sync_chain` is where the building blocks are wired together:

```rust
let summary = client.sync_state().await?;
```

For custom sync flows the building blocks are public on `Client`:

```rust
use miden_client::sync::{StateSync, StateSyncInput, StateSyncUpdate};

// build_sync_input() collects tracked account headers, all unique note tags,
// all unspent input & output notes, and all uncommitted transactions.
let mut input: StateSyncInput = client.build_sync_input().await?;
input.note_tags.insert(extra_tag); // note_tags is a BTreeSet<NoteTag>

// Construct a StateSync with the same rpc / note-screener the client uses
// internally, fetch the current PartialMmr, and drive the sync. This part
// mirrors Client::sync_chain's body in crates/rust-client/src/sync/mod.rs:
//
//   let state_sync = StateSync::new(rpc_api, Arc::new(note_screener), tx_discard_delta);
//   let mut partial_mmr = client.get_current_partial_mmr().await?;
//   let update: StateSyncUpdate = state_sync.sync_state(&mut partial_mmr, input).await?;
//
// Persist the result. `Client::apply_state_sync` writes the update to the
// store and prunes irrelevant blocks. (Note: unlike `sync_chain`, this
// convenience does NOT re-cache the PartialMmr; if you rely on the in-memory
// MMR cache, replicate sync_chain's cache_partial_mmr step yourself.)
client.apply_state_sync(update).await?;
```

`StateSync::new(rpc_api, note_screener, tx_discard_delta)`,
`Client::get_current_partial_mmr()`, and
`StateSync::sync_state(&mut partial_mmr, input)` are the load-bearing pieces —
copy that construction from `Client::sync_chain` rather than reinventing it.

## no_std Compatibility

The `rust-client` crate is `no_std`. Follow these rules:

### Imports

Declare `#![no_std]` and pull in `alloc` (and `std` only under the feature);
use `alloc::` / `core::` paths instead of `std::`:

```rust
#![no_std]

#[macro_use]
extern crate alloc;
use alloc::boxed::Box;

#[cfg(feature = "std")]
extern crate std;
```

Within modules, import the collection/string/fmt types you need from `alloc`
/ `core` (e.g. `alloc::string::String`, `alloc::vec::Vec`, `core::fmt`).

### Feature Flags

Gate `std`-only dependencies behind the `std` feature. `default = ["std"]`,
and `std` re-exports `concurrent` plus the `std` features of upstream crates:

```toml
[features]
concurrent = ["miden-tx/concurrent"]
default = ["std"]
std = [
  "concurrent",
  "miden-protocol/std",
  "tonic/transport",
  # ...plus tokio, tempfile, and other upstream `std` features
]
```

Note `miden-tx/concurrent` is pulled in indirectly via the `concurrent`
feature rather than listed directly under `std`.

### Platform-Specific Code

Use `#[cfg_attr]` for WASM vs native differences:

```rust
#[cfg_attr(not(target_arch = "wasm32"), async_trait::async_trait)]
#[cfg_attr(target_arch = "wasm32", async_trait::async_trait(?Send))]
```

## Public API Documentation

### Module-Level Docs

Start every module file with `//!` documentation:

```rust
//! Provides the client APIs for synchronizing the client's local state with the Miden
//! network.
//!
//! ## Overview
//!
//! This module handles the synchronization process between the local client and the
//! Miden network.
//!
//! ## Examples
//!
//! ```rust,ignore
//! let sync_summary: SyncSummary = client.sync_state().await?;
//! ```
```

### Function/Method Docs

- One-line summary starting with a verb
- Detailed explanation if non-obvious
- `# Errors` section listing error conditions
- Use backtick references: `[`Type`]`
- Aim for ~100 character line length in doc comments

```rust
/// Adds the provided [`Account`] in the store so it can start being tracked.
///
/// # Errors
///
/// - If the account is new but it does not contain the seed.
/// - If the account is already tracked and `overwrite` is set to `false`.
pub async fn add_account(
    &mut self,
    account: &Account,
    overwrite: bool,
) -> Result<(), ClientError> {
```
