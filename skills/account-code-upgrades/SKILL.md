---
name: account-code-upgrades
description: Implement and validate code upgrades for existing Miden accounts on v0.17. Use when making an account upgradeable, building an account-code upgrade transaction, or sending an UpgradeNote to a network account. General release migrations belong in rust-sdk-source-guide.
---

# Account Code Upgrades

In v0.17, `native_account::upgrade` actually replaces account code; in v0.16 it
only recorded the requested commitments. The old code authenticates the transaction,
and the new code takes effect afterward in the epilogue.

## Establish the upgrade path

Inspect the account's current components, authority (including its frozen state), authentication and storage before
building a request. The account must already be deployed and have an authorized upgrade
entrypoint, normally `UpgradeManager` plus `Authority`. Adding these components to the
replacement code cannot make an account without an upgrade entrypoint upgradeable.

- **Directly authenticated account with `Authority::AuthControlled`:** use the client's
  `build_account_code_upgrade` request helper.
- **`OwnerControlled` or `RbacControlled`:** the upgrade must be called from a note;
  authority checks the note's sender. A direct transaction script cannot substitute for it.
- **Network account:** use `UpgradeNote` with owner- or role-controlled authority.
  Never combine an allowlisted UPGRADE note with `UpgradeManager`, `AuthControlled`
  and `AuthNetworkAccount`: that combination lets any note sender replace the code.

Storage is unchanged by an upgrade. Build the replacement `AccountCode` from the intended
components and verify it can use the existing slot names, types and contents. Preserve
authentication, access control and an upgrade entrypoint if future upgrades are intended.
The kernel validates code structure and commitment, not storage compatibility.

## Direct client request

For an existing single-signature account with `UpgradeManager` and `AuthControlled`:

```rust
use miden_client::transaction::TransactionRequestBuilder;

client.sync_state().await?;
let request = TransactionRequestBuilder::new()
    .build_account_code_upgrade(new_code)?; // owned AccountCode
client.submit_new_transaction(account.id(), request).await?;
```

Use a fresh builder: this helper replaces its custom script and script argument, and
rejects own output notes or an explicit expiration delta. For multisig, prepare the
v0.17 `MultisigAuthArgs`, advice and bound block on the builder as described in
`rust-client-patterns`, then call the upgrade helper.

`.account_code_upgrade(code)` only supplies the code preimage; it does not initiate
an upgrade. A custom transaction must also call the upgrade entrypoint with
`[NEW_CODE_COMMITMENT, EMPTY_WORD]`. With the lower-level executor, supply the code through
`TransactionArgs::with_account_code_upgrade(AccountCodeUpgrade::new(code))`.
Guest SDK 0.15 has no `native_account::upgrade` Rust binding; use the standards MASM
entrypoint through the host request or an authorized note.

## Network upgrade note

The target must be an existing public network account. Install `UpgradeManager` and
owner/RBAC authority when creating an upgradeable account. Before sending an upgrade,
allowlist `UpgradeNote::script_root()` in `AuthNetworkAccount`; the default allowlist
excludes UPGRADE. Configure the target's fee policy to accept it: a constant-fee policy
needs a fee schedule entry, while a custom policy needs its own coverage checks.

On a deployed account, use an existing authorized administration path. Adding the root
with `NetworkAccountConfigNote` requires that config note to be allowed already. Changing
a constant-fee entry with `ConstantFeePolicyConfigNote` requires `ConstantFeeManager`
and an allowed, priced config note. Wait for the configuration transactions to commit
before consuming UPGRADE: network authentication reads the initial account state.

Fund the target for native execution fees and the sender for any per-note fee and its
own transaction fees. Positive per-note fees require a bound `FEE_SPONSORSHIP` note;
standard sender authentication creates it automatically. Check fee-asset compatibility
instead of duplicating sponsorship or assuming the target's vault alone covers the fee.

```rust
use miden_client::transaction::TransactionRequestBuilder;
use miden_standards::note::UpgradeNote;

let note = UpgradeNote::builder()
    .sender(authorized_sender.id())
    .target(network_account.id())
    .code(new_code)
    .serial_number(serial) // fresh note serial number
    .build()?;
let request = TransactionRequestBuilder::new()
    .own_output_notes(vec![note.into()])
    .build()?;
```

Execute the publishing request against `authorized_sender`, the current owner or an
account with the required RBAC role. The network account applies the upgrade in its
later consuming transaction; publishing the note alone does not complete the upgrade.

The builder makes the note public and supplies the target and code attachments. Keep
those attachments intact. All attachments share a 512-word/four-attachment limit;
the target uses one word, and code chunks use up to 256 words each. Handle builder
errors when the encoded code does not fit. Avoid also supplying a different encoding
of that code in the consuming transaction's advice map.

## Validate the result

- Storage upgrades are unsupported: `STORAGE_UPGRADE_COMMITMENT` must be empty.
  Empty or unchanged code commitments are no-ops; only one upgrade may be pending
  per transaction, and an account cannot be upgraded in its creation transaction.
- Exercise the authorized path and rejection of an unauthorized sender in MockChain.
  Verify the resulting code commitment, retained application storage and non-fee assets,
  authentication, and expected nonce/fee changes.
  Execute a subsequent transaction through the new code; the upgrade transaction itself
  still runs the old code. Use `rust-sdk-testing-patterns` for account-patch handling.
- For live validation, sync until the upgrade transaction commits. For network accounts,
  also verify the upgrade note was consumed and exercise the new code through an allowed
  note/script path. Compare the account's resulting code commitment with the intended
  replacement before reporting success.

## Released references

- [Client request builders](https://github.com/0xMiden/rust-sdk/blob/v0.17.2/crates/rust-client/src/transaction/request/builder.rs)
- [UpgradeNote and attachment handling](https://github.com/0xMiden/protocol/blob/v0.17.1/crates/miden-standards/src/note/upgrade.rs)
- [Network-account configuration](https://github.com/0xMiden/protocol/blob/v0.17.1/crates/miden-standards/src/note/config/network_account_config.rs) and [constant-fee configuration](https://github.com/0xMiden/protocol/blob/v0.17.1/crates/miden-standards/src/note/config/constant_fee_policy_config.rs)
- [Upgrade entrypoint and authority check](https://github.com/0xMiden/protocol/blob/v0.17.1/crates/miden-standards/asm/standards/account_upgrade.masm)
- [Account upgrade migration](https://github.com/0xMiden/docs/blob/9911d004142687ad7d06f72aa03284df54ae9922/docs/builder/migration/03-account-changes.md)
