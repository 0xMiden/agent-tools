---
name: masm-proc-type-signatures
description: Enforce type-signature conventions for public Miden Assembly (.masm) procedures. Use when adding, editing, or reviewing a `pub proc` signature — parameter and return types, semantic type aliases, struct/array/tuple types, and how the signature maps onto the operand stack and the doc-comment Inputs/Outputs.
---

# MASM Procedure Type Signatures

## Overview

Public MASM procedures carry a type signature on the `pub proc` line, mirroring the Rust API:

```masm
pub proc get_map_item(slot_id: StorageSlotId, key: StorageMapKey) -> word
```

The signature names each stack input as a typed parameter and declares the return type, using semantic aliases (`AccountId`, `NoteRecipient`, `AssetAmount`, …) named after the corresponding Rust types. It is **ABI/AST metadata only**: adding or changing a signature does not change the procedure's behavior, its MAST root, or the transaction-kernel commitment. The signature complements — it does not replace — the doc-comment `Inputs:` / `Outputs:` stack notation.

## Syntax

The signature attaches to the procedure name, after any `@`-attributes and after the doc comment:

```masm
#! ...doc comment...
#!
#! Invocation: exec
pub proc name(param_a: TypeA, param_b: TypeB) -> ReturnType
    ...
end
```

- **No parameters:** keep the empty parens — `pub proc get_nonce() -> felt`.
- **No return value:** omit the arrow — `pub proc mint(asset: Asset)`.
- **Multiple return values:** a tuple — `pub proc find_attachment(attachment_scheme: u16) -> (Bool, u8)`.
- **Long signatures** may wrap across lines:

```masm
@locals(6)
pub proc execute_foreign_procedure(
    foreign_account_id: AccountId,
    foreign_proc_root: AccountProcedureRoot,
    foreign_procedure_inputs: [felt; 16]
) -> [felt; 16]
```

Attributes (`@locals(N)`, `@auth_script`, `@account_procedure`, …) stay on their own lines immediately before `pub proc`; the signature is part of the `pub proc` line.

In v0.17, `@account_procedure`, `@auth_script`, `@note_script`, and `@transaction_script`
imply `@callconv("component-model")`. Keep only one of these ABI attributes on a procedure;
a different explicit calling convention or a second ABI attribute is a parse error.

## Type vocabulary

Prefer the most specific **semantic alias** that fits; fall back to a primitive only when no domain type applies.

Primitives:
- `felt` — a single field element (generic value: a nonce, a raw commitment element).
- `word` — 4 felts (a generic commitment, hash, or root with no dedicated newtype).
- `u8`, `u16`, `u32` — sized integers (counts, indices, deltas, tags).
- `u256` — now a built-in type; replaces `miden::core::math::u256::u256`.
- `ptr<T>` — a typed pointer, such as `ptr<felt>` or `ptr<Asset>`; replaces the removed protocol `MemoryAddress` alias.
- `i1` — a single-bit boolean (aliased as `Bool`).
- `[felt; N]` — a fixed-size span of N felts that is a *real* input/output (not padding).
- `struct { field: T, ... }` — an ordered group of typed fields.
- `(T, U, ...)` — a tuple return of multiple values.

Semantic aliases (defined in `types.masm`, see below):
- Two-felt identifiers: `AccountId`, `StorageSlotId` (`struct { suffix: felt, prefix: felt }`).
- Word newtypes: `AssetId`, `AssetValue`, `AccountProcedureRoot`, `StorageMapKey`, `NoteRecipient`, `NoteMetadata`, `NoteScriptRoot`, `TransactionScriptRoot`.
- Composite: `Asset` (`struct { id: AssetId, value: AssetValue }`), `DoubleWord` (`struct { lo: word, hi: word }`; fields were `word_lo` / `word_hi` in v0.16).
- Scalars: `AssetAmount` (felt), `NoteTag` / `BlockNumber` (u32), `Bool` (i1).
- `NoteType` is now `enum NoteType : u8 { PRIVATE = 0, PUBLIC = 1 }`; its values are unchanged.

Use bare `word` / `felt` for generic commitments, hashes, roots, nonces, counts, and timestamps that have no dedicated domain type; use the newtype whenever one exists for the concept.

## Stack ordering and flattening

The signature must describe the same stack the doc comment does. Rules:

- **Parameters are listed top-of-stack first.** The first parameter sits on top of the operand stack, the next below it, and so on. Return values follow the same order (first tuple element on top).
- **Structs flatten field-0-on-top.** `AccountId = struct { suffix, prefix }` puts `suffix` on top and `prefix` below, so `get_id() -> AccountId` yields `[account_id_suffix, account_id_prefix]`. `Asset = struct { id: word, value: word }` puts the id word on top of the value word.
- **Padding is excluded from signatures.** `pad(N)` never appears as a parameter or return type, even though the doc-comment Inputs/Outputs still show it (matching the `tx_prepare_fpi` / `call`-convention precedent). A `call` entrypoint whose doc reads `Inputs: [SCRIPT_ROOT, pad(12)]` has the signature `(script_root: word)`.
- **Real fixed spans are included.** A genuine 16-felt argument is `[felt; 16]` in the signature and `foreign_procedure_inputs(16)` in the doc — that is data, not padding.

## Relationship to the doc comment

Signature and doc comment must agree on order and count, but use different naming styles — keep both:

- Signature parameter/field names are lowercase `snake_case` regardless of width: `recipient: NoteRecipient`, `asset: Asset`, `key: StorageMapKey`.
- Doc-comment stack names follow `masm-doc-comments`: single felts lowercase (`tag`, `note_index`), words UPPERCASE (`RECIPIENT`, `KEY`), split identifiers `account_id_{suffix,prefix}`, spans `name(N)`.

So `create(tag: NoteTag, note_type: NoteType, recipient: NoteRecipient) -> u16` pairs with `Inputs: [tag, note_type, RECIPIENT]`. The `Where:` bullets still describe every item; the signature does not remove the need for them.

## Declaring a new type alias

Add aliases to the protocol type modules rather than inlining `struct { ... }` at each proc:

- `crates/miden-protocol/asm/protocol_utils/src/types.masm` — shared type definitions, now including the protocol-library types as well as the transaction-kernel types.
- `crates/miden-protocol/asm/protocol/src/types.masm` — re-exports those definitions, so `use ... from miden::protocol::types` still works.

Declare with `pub type`, and add a short comment when the stack layout is non-obvious (which felt is on top):

```masm
# Two-felt identifier (suffix on top of the stack, prefix below).
pub type StorageSlotId = struct { suffix: felt, prefix: felt }

pub type NoteTag = u32
```

Name the alias after the Rust type it mirrors so a signature reads like the Rust API. When a type already exists, reuse it — do not introduce a second alias for the same concept.

## Scope

Every public procedure (`pub proc`) should carry a signature — for both `exec` and `call`/`dyncall` invocation styles (padding is excluded for the latter). Private `proc`s may carry one when it aids clarity but are not required to. Adding signatures to existing untyped `pub proc`s is a safe, root-preserving change.

## v0.17 stack contracts

Audit custom auth and fee code against the released standards sources:

| Procedure | Input prefix in v0.17 |
|---|---|
| `tx::get_block_commitment` | `[block_number]`; use `get_reference_block_commitment` for the zero-argument form |
| `guardian::verify_signature` | `[is_rotation, MSG]`; obtain the flag from `assert_rotation_policy` before executing notes |
| `fee::pay_fee` | `[num_extra_cycles, CONVERSION_INFO, serial_number_block]` |
| `fee::create_and_fund_fee_note` | `[serial_number_block, ASSET_ID, ASSET_VALUE]` |
| `auth::create_tx_summary` | `[user_params(6)]` |
| `auth::create_tx_summary_with_block` | `[block_number, user_params(6)]` |
| `tx_policy::assert_no_output_notes` | `[]`; call before creating the fee note |

Summary creation returns `[PARAMS_HEAD, PARAMS_TAIL, ACCOUNT_DELTA_COMMITMENT,
INPUT_NOTES_COMMITMENT, OUTPUT_NOTES_COMMITMENT, BLOCK_COMMITMENT]`. Historical
block lookups require that block in authenticated transaction inputs. Passing the
old own-note count as `is_rotation` is especially dangerous: `1` skips guardian
signature verification. See the [v0.17 MASM migration guide](https://github.com/0xMiden/docs/blob/9911d004142687ad7d06f72aa03284df54ae9922/docs/builder/migration/08-masm-changes.md).

## Validation checklist

- [ ] Every `pub proc` has a signature: `()` when it takes no inputs, no `->` when it returns nothing.
- [ ] Parameters are listed top-of-stack first; return order matches (first item on top).
- [ ] Structs flatten field-0-on-top; the flattened order matches the doc-comment Inputs/Outputs.
- [ ] `pad(N)` does not appear in the signature; real spans use `[felt; N]`.
- [ ] The most specific semantic alias is used; bare `word`/`felt` only for generic commitments/counts with no domain type.
- [ ] New aliases are declared with `pub type` in the appropriate `types.masm`, named after the Rust type, with a layout comment when non-obvious.
- [ ] The doc-comment `Inputs:`/`Outputs:` and `Where:` sections are still present and consistent with the signature (see `masm-doc-comments`).
