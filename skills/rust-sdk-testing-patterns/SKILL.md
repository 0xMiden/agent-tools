---
name: rust-sdk-testing-patterns
description: Guide to testing Miden smart contracts with MockChain. Covers test setup, contract building, account/note creation, transaction execution, storage verification, faucet setup, output note verification, block numbering, multi-transaction tests, and asset-bearing notes. Use when writing, editing, or debugging Miden integration tests.
---

# Miden Testing Patterns (MockChain)

These patterns target `miden-protocol` / `miden-standards` / `miden-testing` `0.16.0-rc.9` with
`miden-client` `0.16.0-rc.5`. Write the full pre-release strings — Cargo does not match a
pre-release against a plain `"0.16"` requirement.

`MockChain` and its builders live in `miden-testing`, which is also re-exported as
`miden_client::testing` behind the client's optional `testing` feature. A test crate must either
enable that feature or depend on `miden-testing` directly.

The canonical worked examples are in the protocol repo itself:
`crates/miden-testing/src/kernel_tests/tx/test_note.rs` for the end-to-end MockChain flow, and
`crates/miden-testing/src/mock_chain/{chain,chain_builder}.rs` for the full builder surface.

## Test File Setup

All tests are async and use MockChain for local execution without a network.

```rust
use miden_client::{
    account::{
        component::{InitStorageData, StorageValueName},
        AccountBuilder, AccountComponent, AccountType, StorageSlotName,
    },
    auth::AuthSchemeId,
    note::NoteAssets,
    transaction::RawOutputNote,
    Felt, Word,
};
use miden_client::asset::{Asset, FungibleAsset};
use miden_testing::{AccountState, Auth, MockChain};
```

`StorageValueName` lives under `account::component`, never under `account::` directly.

## Step-by-Step Test Pattern

### 1. Initialize MockChain Builder

`let mut builder = MockChain::builder();`

### 2. Create Sender/Wallet Accounts

For a bare wallet, `builder.add_existing_wallet(Auth::BasicAuth { auth_scheme: AuthSchemeId::Falcon512Poseidon2 })`.
For a pre-funded one, `builder.add_existing_wallet_with_assets(auth, [FungibleAsset::new(faucet.id(), 100)?.into()])`.
Both return `anyhow::Result<Account>`.

`Auth` also offers `Multisig`, `GuardedMultisig`, `MultisigSmart`, `IncrNonce`, `Noop`,
`Conditional` and `NetworkAccount` variants, plus the shorthands `Auth::default()`,
`Auth::basic_falcon()` and `Auth::basic_ecdsa()`.

> Auth-scheme naming: `miden_client::auth` re-exports the **same** protocol enum under two names —
> `AuthScheme` (the protocol name) and `AuthSchemeId` (an alias). Both compile; the field is
> `Auth::BasicAuth { auth_scheme }`. The enum is `#[non_exhaustive]` with `Falcon512Poseidon2 = 2`
> and `EcdsaK256Keccak = 1`, and the constants `RPO_FALCON_SCHEME_ID` /
> `ECDSA_K256_KECCAK_SCHEME_ID` name them.

### 3. Set Up Faucets (for fungible assets)
```rust
let faucet = builder.add_existing_basic_faucet(
    Auth::BasicAuth {
        auth_scheme: AuthSchemeId::Falcon512Poseidon2,
    },
    "TOKEN",     // token symbol
    1000,        // max supply
    Some(10),    // token_supply (None defaults to 0)
)?;
```

The 4th argument is `token_supply: Option<u64>` (an explicit `None` is treated as `0`).

### 4. Build Contracts

Build contracts **out of process** with the `cargo miden build` CLI and load the resulting `.masp`
package in the test. This keeps contract compilation separate from the test binary's client
dependencies. At `sdk/v0.14.0`, the compiler's internal matrix uses
`miden-protocol =0.16.0-rc.4` and the VM `0.29` line; do not replace the test crate's client pins
with that internal matrix.

Package artefacts: the extension is `.masp` (`Package::EXTENSION`), magic `MASP\0`, package format
version `[6, 0, 0]`, MAST wire version `[0, 0, 4]`. There is no `.masl`.

### 5. Create Account with Storage

**Storage slot naming convention** (CRITICAL):
```
<package_name>::<interface_segment>::<field_name>
```

The slot name is part of the on-chain storage ABI and is derived by the compiler's
`#[component_storage]` macro, **not** from the Rust struct name:
- `<package_name>` is the **bare** package name (`[package].name` in `miden-project.toml`), with no
  `miden:` org prefix.
- `<interface_segment>` is the `[lib].namespace` **interface** segment — the text between the last
  `/` and the `@` in the namespace — snake_cased. Because it comes from the declared namespace,
  renaming the Rust struct cannot change the deployed slot name.
- `<field_name>` is the Rust storage field's identifier (not its `description`).

Characters outside `[A-Za-z0-9_]` are replaced with `_` in each segment.

Live values from the pinned compiler examples: `counter_contract::counter_contract::count_map`,
`auth_component_rpo_falcon512::auth_component::owner_public_key`.

The component's storage is declared with the three-part component macro (`#[component_storage]`
struct + `#[component]` trait + `#[component]` impl); the storage struct, not the trait, carries the
`#[storage]` fields the slot names derive from. Externally-callable trait methods additionally need
`#[account_procedure]`. See the `rust-sdk-patterns` skill for the contract side.

Seed any value slot that has no schema default, then register the account:

```rust
// A `StorageValue<Word>` slot with no schema default must be seeded, or
// `AccountComponent::from_package` errors with `InitValueNotProvided`.
// A map slot defaults to empty and needs no entry.
let initialized_slot = StorageSlotName::new("bank_account::bank::initialized")?;

let mut init_storage_data = InitStorageData::default();
init_storage_data.insert_value(
    StorageValueName::from_slot_name(&initialized_slot),
    Word::default(),
)?;

let component = AccountComponent::from_package(&bank_package, &init_storage_data)?;

let account_builder = AccountBuilder::new([3u8; 32])
    .account_type(AccountType::Public)
    .with_component(component);

let bank_account = builder.add_account_from_builder(
    Auth::BasicAuth { auth_scheme: AuthSchemeId::Falcon512Poseidon2 },
    account_builder,
    AccountState::Exists,
)?;
```

**There is no `AccountBuilder::with_auth_component`.** Auth components are installed like any other
component, via `.with_component(..)` / `.with_components(..)`. The builder's surface is
`new([u8; 32])`, `version`, `account_type`, `with_asset_callbacks`, `with_component(s)`,
`with_assets`, `nonce`, `storage_schemas`, `build`, `build_existing`.

For map slots, seed entries with `init_storage_data.insert_map_entry(slot_name, key, value)?`.

> Storage-seeding footgun: `InitStorageData::insert_value(name, value)` takes
> `value: impl Into<WordValue>`. The numeric `From` impls (`u8`/`u16`/`u32`/`u64`) produce a
> `WordValue::Atomic(string)` that the slot's schema parses — **not** a felt-positioned `Word`. Only
> `From<Felt>` yields `[felt, 0, 0, 0]`, and `From<Word>` / `From<[Felt; 4]>` / `From<[u32; 4]>` are
> fully-typed words. For a `StorageValue<Word>` slot whose contract reads index `[0]`, seed a `Word`
> (`Word::default()` for zero). The `insert_value` doc comment claiming `u64` becomes `[0,0,0,felt]`
> is inaccurate; the code produces an atomic string.

> Account model:
> - `AccountType` is the visibility enum `{ Private (default), Public }`, with `as_u8()`,
>   `is_public()`, `is_private()`.
> - Set visibility via `.account_type(..)`. There is no `.storage_mode(..)` and no
>   `AccountStorageMode` on this builder.
> - Faucet-ness is determined by the installed components.

`MockChainBuilder` also ships ready-made account helpers that remove most of the above:
`create_new_wallet`, `add_existing_note_creator`, `add_existing_non_fungible_faucet`,
`add_existing_network_faucet`, `create_new_faucet`, `add_existing_mock_account` (and its
`_with_storage` / `_with_assets` / `_with_storage_and_assets` variants),
`add_existing_account_from_components`.

### 6. Create Notes

Build a note with `NoteBuilder`, seeding the `RandomCoin` from the note-script root:

```rust
use miden_client::{asset::FungibleAsset, crypto::RandomCoin, note::NoteScript, Felt, Word};
use miden_standards::testing::note::NoteBuilder;

let note_script = NoteScript::from_package(note_package.as_ref())?;
let mut note_rng = RandomCoin::new(Word::from(note_script.root()));
let note = NoteBuilder::new(sender.id(), &mut note_rng)
    .package((*note_package).clone())
    .add_assets([FungibleAsset::new(faucet.id(), 50)?.into()])
    .note_storage([Felt::from(42_u32), Felt::from(0_u32)])?
    .build()?;
```

`NoteBuilder::new(sender: AccountId, rng: T)` takes the RNG **by value**; `&mut RandomCoin` works
because `&mut T: Rng`. Other builder methods: `package`, `script`, `code`, `note_type`, `tag`,
`add_assets`, `note_storage`, `serial_number`, `attachment`, `advice_map`,
`dynamically_linked_packages`, `source_manager`, `build`.

> `.tag(..)` takes a **`u32`**, not a `NoteTag`. The idiom is
> `.tag(NoteTag::with_account_target(account.id()).into())`.

> `NoteScript::from_package(&Package)` requires the package to have exactly one `@note_script`
> export. `NoteScript::root()` returns a `NoteScriptRoot` newtype, and `RandomCoin::new` needs a
> `Word`, so convert explicitly with `Word::from(...root())`.

> `Felt::new(u64)` is **fallible** — it returns `Result<Felt, FeltFromIntError>`. `note_storage`
> takes `impl IntoIterator<Item = Felt>`, so build each felt with the infallible
> `Felt::from(42_u32)` for in-range literals (`From<u8>/<u16>/<u32>` are infallible); for an
> arbitrary `u64`, use `Felt::new(n)?`. Use `Felt::new_unchecked(n)` only after proving
> `n < Felt::ORDER`.

> A note carries at most `MAX_ASSETS_PER_NOTE` = **16** assets.

`MockChainBuilder` also has ready-made note constructors that skip `NoteBuilder` entirely:
`add_p2any_note`, `add_p2id_note`, `add_p2ide_note`, `add_swap_note`, `add_spawn_note`,
`add_tx_fee_note`, `add_p2id_note_with_fee`.

Standard notes built outside the chain builder use typed `bon` builders —
`P2idNote::builder().sender(..).target(..).serial_number(..).asset(..).build()?`, then
`Note::from(p2id)`. There is no `XNote::create(..)`.

### 7. Add to MockChain and Build

Register accounts (`builder.add_account(account)?`) and seed notes
(`builder.add_output_note(RawOutputNote::Full(note.clone()))`), then `let mut mock_chain = builder.build()?;`.

> `add_output_note` returns `()`, not a `Result` — no `?`.

### 8. Execute Transaction

```rust
let executed = mock_chain
    .build_transaction(account.id())
    .authenticated_input_note(note.id())
    .build()?
    .execute()
    .await?;

mock_chain.add_pending_executed_transaction(&executed)?;
mock_chain.prove_next_block()?;
```

`build_transaction(input)` takes `impl Into<MockTransactionInput>`, which has `From<AccountId>` and
`From<Account>`. Pass an `Account` (rather than an id) when chaining transactions against evolving
in-memory state, and for private accounts.

Input notes are **not** positional arguments. Attach them with `.authenticated_input_note(NoteId)`,
`.authenticated_input_notes(..)`, `.unauthenticated_input_note(Note)` or
`.unauthenticated_input_notes(..)`.

`build()` is sync and returns `anyhow::Result<MockTransaction>`; `execute()` is on `MockTransaction`,
is `async`, and returns `Result<ExecutedTransaction, TransactionExecutorError>`.

Other `MockTransactionBuilder` methods: `tx_script`, `tx_script_args`, `auth_args`,
`extend_note_args`, `reference_block`, `foreign_accounts`, `extend_advice_inputs`,
`add_advice_map_entry`, `authenticator`, `add_signature`, `add_note_script`, `send_notes_script`,
`expected_output_note(s)`, `with_source_manager`.

### 9. Execute with Transaction Script

`TransactionScript::from_package(&package)?` handles a `kind = "tx-script"` package directly: if the
package is a program it uses the entrypoint, otherwise it looks for the single procedure carrying
the `transaction_script` attribute, which the compiler emits on tx-script exports.

```rust
use miden_client::transaction::TransactionScript;

let tx_script = TransactionScript::from_package(&tx_script_package)?;

let executed = mock_chain
    .build_transaction(account.id())
    .tx_script(tx_script)
    .build()?
    .execute()
    .await?;

mock_chain.add_pending_executed_transaction(&executed)?;
mock_chain.prove_next_block()?;

let updated_account = mock_chain.committed_account(account.id())?;
```

`TransactionScript::from_parts(Arc<MastForest>, MastNodeId)` exists, but it is not the path for
compiler-produced tx-script packages — use the package-based construction shown above.

### 10. Verify Storage State

Read state with `account.storage().get_item(&slot)` or
`account.storage().get_map_item(&slot, key)` on an in-memory `Account` you keep patch-current, or
re-fetch the committed account with `mock_chain.committed_account(account.id())?` after
`prove_next_block()`.

> `get_map_item(&self, slot_name: &StorageSlotName, key: StorageMapKey)` takes a **`StorageMapKey`
> by value**, not a `Word`. Build one with `StorageMapKey::new(word)`, or `StorageMapKey::empty()` /
> `StorageMapKey::from_index(idx)` for the degenerate cases.

`AccountStorage` exposes scalar felt values in `[felt, 0, 0, 0]` layout.

`FungibleAsset::amount()` returns an **`AssetAmount`**, not a `u64` — an assertion comparing it to a
bare integer will not compile. Use `AssetAmount::new(expected)?` or `.as_u64()`.

### 11. Verify Output Notes

`add_output_note()` is only on `MockChainBuilder` (before `build()`) — use it to seed the chain with
existing notes. To assert on notes a transaction *produces*, use `expected_output_note(..)` /
`expected_output_notes(..)` on `MockTransactionBuilder`:

```rust
use miden_client::{
    note::{Note, NoteType, PartialNoteMetadata},
    transaction::RawOutputNote,
};

let partial_metadata = PartialNoteMetadata::new(sender, NoteType::Public).with_tag(tag);
let expected_note = Note::new(expected_assets, partial_metadata, expected_recipient);

let executed = mock_chain
    .build_transaction(account.id())
    .authenticated_input_note(note.id())
    .expected_output_note(RawOutputNote::Full(expected_note))
    .build()?
    .execute()
    .await?;
```

> Both `expected_output_note(s)` silently **drop** `RawOutputNote::Partial` entries — only `Full`
> notes are retained and checked.

> Note metadata:
> - `Note::new(assets, partial_metadata, recipient)` takes a `PartialNoteMetadata` (sender/type/tag
>   only), is infallible, and has no `Into` conversion on that parameter.
> - `PartialNoteMetadata::new(sender, note_type)` defaults the tag to `NoteTag::default()`; set one
>   with `.with_tag(tag)` or `set_tag(..)`.
> - For attachment-bearing notes use
>   `Note::with_attachments(assets, partial_metadata, recipient, attachments)`.

## Multi-Transaction Test Pattern

For contracts requiring initialization before use, each step usually needs its own `execute()` →
`add_pending_executed_transaction()` → `prove_next_block()` cycle.

When you keep reading from and reusing the **same in-memory `Account`** across transactions, apply
the account patch after every `execute()` so later local reads see the new state:

```rust
bank_account.apply_patch(executed.account_patch())?;
```

`Account::apply_patch(&AccountPatch)` and `ExecutedTransaction::account_patch() -> &AccountPatch`
are the account-update path. If you instead re-fetch via `mock_chain.committed_account(..)` after
`prove_next_block()`, you can skip the patch entirely.

> **The one exception that catches people out:** `TransactionSummary::account_delta()` still returns
> a relative `AccountDelta` and is deliberately *not* a patch. A blanket rename of `account_delta`
> to `account_patch` breaks that call site.

## MockChain Block Numbering

Genesis is block 0. Each `prove_next_block()` advances the block number by 1; `prove_next_block_at(timestamp)`
does the same at a chosen timestamp. In contract code, `tx::get_block_number()` returns the
**reference block** — the last proven block at the time the transaction started, not the block the
transaction will be included in.

> `tx::get_block_number()` returns a **`BlockNumber`**, not a `Felt`. Compare it directly against
> another `BlockNumber`; convert a felt read out of note storage with `BlockNumber::try_from(felt)`.

## Asset-Bearing Note Example

1. Create a `FungibleAsset` from a faucet ID and amount, e.g. `FungibleAsset::new(faucet.id(), 50)?`
   (the amount parameter is still `u64`), and wrap it into `NoteAssets::new(vec![Asset::Fungible(asset)])?`
   — or pass it via `NoteBuilder::add_assets`.
2. Seed a `RandomCoin` from `Word::from(NoteScript::from_package(note_package.as_ref())?.root())`.
3. Pass any note inputs into `note_storage(...)?`, building each felt with the infallible
   `Felt::from(_u32)` for in-range literals or checked `Felt::new(n)?` for arbitrary `u64` inputs.
4. Finish with `.package((*note_package).clone()).build()?`.

The faucet must be set up first (see Step 3) and the sender wallet must hold sufficient assets
(see Step 2).

## Key Dependencies

```toml
miden-client    = "0.16.0-rc.5"   # with features = ["testing"] for miden_client::testing
miden-protocol  = "0.16.0-rc.9"
miden-standards = "0.16.0-rc.9"
miden-testing   = "0.16.0-rc.9"
```

The contracts a test builds depend on the guest SDK `miden = "0.14.0"`, built with
`cargo-miden` / `midenc` `0.10.0` on the pinned nightly (`nightly-2026-09-01`, target
`wasm32-wasip2`). See Step 4 for the out-of-process build pattern.

## Validation Checklist

- [ ] Test function is `async` and uses `#[tokio::test]`
- [ ] `miden-testing` is available — either the client's `testing` feature or a direct dependency
- [ ] Auth uses `AuthSchemeId::Falcon512Poseidon2` (or the equivalent `AuthScheme::Falcon512Poseidon2`)
- [ ] `AccountBuilder` uses `.account_type(..)`, and no `.storage_mode(..)` and no `.with_auth_component(..)` — auth goes through `.with_component(..)`
- [ ] Storage slot names follow `<package_name>::<interface_segment>::<field_name>`
- [ ] Value slots without a schema default are seeded via `InitStorageData::insert_value(StorageValueName::from_slot_name(&slot), ..)`; `StorageValue<Word>` slots get a `Word`, not a bare integer
- [ ] Contracts are built out of process with `cargo miden build`, not by depending on `cargo-miden`
- [ ] `NoteScript::root()` converted with `Word::from(..)` before seeding `RandomCoin`
- [ ] `NoteBuilder::tag(..)` is passed a `u32`
- [ ] Note-storage felts built with infallible `Felt::from(_u32)` or checked `Felt::new(n)?` for arbitrary `u64` inputs
- [ ] `Note::new(..)` is passed a `PartialNoteMetadata` (not `NoteMetadata`)
- [ ] Transaction scripts built with `TransactionScript::from_package(&package)?`
- [ ] Execution goes through `chain.build_transaction(..)` with `.authenticated_input_note(..)` / `.unauthenticated_input_note(..)`, then `.build()?.execute().await?`
- [ ] `prove_next_block()` called after `add_pending_executed_transaction()`
- [ ] In-memory accounts refreshed with `account.apply_patch(executed.account_patch())?`, and `TransactionSummary::account_delta()` left alone
- [ ] Map reads pass a `StorageMapKey`, not a `Word`
- [ ] `FungibleAsset::amount()` compared as `AssetAmount`, not a bare integer
- [ ] Notes added to `MockChainBuilder` via `add_output_note(RawOutputNote::Full(..))` before `build()` (no `?` — it returns `()`)
- [ ] Faucet set up before creating assets
