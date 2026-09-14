---
name: masm-formatting
description: Orchestrator for MASM formatting in 0xMiden/protocol and 0xMiden/miden-vm. Consolidates capitalization, the (N) span family, cross-repo doc comment divergences (plural vs singular Inputs/Outputs, Panics if vs # Panics, named vs string assertion errors), the `Cycles:` section, chained u32 assertion guards, description verbs, and the `miden-format` formatter across the prerequisite MASM skills. Use when editing, reviewing, or creating .masm files.
---

# MASM Formatting

This skill is an orchestrator and gap-filler. It depends on the existing MASM skills and only documents conventions they do not cover plus cross-skill integration guidance. It does not restate prerequisite rules.

## Prerequisites

Consult these skills first.

- `masm-file-structure` – module declarations (`mod` / `pub mod`), section order, and the `@account_procedure` / `@auth_script` / `@note_script` / `@transaction_script` / `@locals(N)` attributes.
- `masm-inline-comments` – inline `#` comments: lowercase start, `# => [...]` stack state, avoid commenting obvious operations.
- `masm-doc-comments` – `#!` doc block: Description, Inputs, Outputs, Where, Panics if, Invocation; singular `is` for single items, plural `are` for composites.
- `masm-proc-type-signatures` – the typed `pub proc name(a: T) -> U` signature line and its semantic type aliases.
- `masm-padding` – `pad(N)` rules for context-switching vs same-context procedures.

## When to Use

Apply this skill alongside the prerequisites whenever you edit a `.masm` file. Reach for it specifically for capitalization questions, `(N)` span notation beyond `pad(N)`, divergences between protocol style and miden-vm style, the `Cycles:` section, chained `u32assert2` guards, and running the `miden-format` formatter.

The conventions below are derived from canonical MASM in [protocol](https://github.com/0xMiden/protocol) and [miden-vm](https://github.com/0xMiden/miden-vm). They apply to anyone writing MASM in the Miden ecosystem, including community contracts, tutorial examples, and library MASM, not just code that lives inside those two repos.

## 1. Capitalization (three tiers)

| Kind | Style | Example |
|---|---|---|
| Word (4 felts) or Word-shaped commitment / root / constant | `UPPER_SNAKE_CASE` | `ASSET_ID`, `ASSET_VALUE`, `FOREIGN_PROC_ROOT`, `EMPTY_WORD` |
| Single felt | `lower_snake_case` | `final_nonce`, `note_idx`, `amount` |
| Multi-felt composite grouped in one name | `lower_snake_case_{part1,part2}` | `account_id_{suffix,prefix}`, `faucet_id_{suffix,prefix}`, `sender_{suffix,prefix}` |

Composite items always use `are` in `Where:` since they name a group of felts, per `masm-doc-comments`.

Part **order** should be stack-top-first, i.e. `{suffix,prefix}`, and source agrees by roughly six to one (82 suffix-first against 14 prefix-first). Write suffix-first in new code; the prefix-first occurrences are legacy.

Brace **spacing** is genuinely split — `{suffix, prefix}` (45) and `{suffix,prefix}` (37) are both common, sometimes within the same file. Match the surrounding file; do not reformat existing braces.

Use `EMPTY_WORD` to denote the all-zero Word `[0, 0, 0, 0]` in stack trackers, `Where:` bullets, and prose comments (e.g. `# => [..., EMPTY_WORD, ...]`). It is primarily a naming convention in stack trackers and prose, conveying *meaning* (absence of data) rather than a literal value — though a few standards modules do define it for real (`const EMPTY_WORD = ZERO_WORD` in `standards/auth/note_script_allowlist.masm`, `standards/auth/tx_script_allowlist.masm` and `standards/fees/fee_manager.masm`).

Canonical references in [protocol](https://github.com/0xMiden/protocol): `crates/miden-protocol/asm/protocol/src/faucet.masm`, `native_account.masm`, `active_note.masm`, `active_account.masm`. (Note that `protocol/src/asset.masm` is a five-line re-export stub — it demonstrates nothing.)

## 2. Stack span notation: the `(N)` family

`pad(N)`, owned by `masm-padding`, is one member of a broader span-size family. `(N)` after an item name denotes a span of N felts, not a Word. Words stay UPPERCASE without `(N)`; spans stay lowercase.

| Use | Example |
|---|---|
| Padding span | `pad(12)`, `pad(15)` |
| Known-size felt-array parameter | `foreign_procedure_inputs(16)`, `foreign_procedure_outputs(16)` |
| Mixed inline tracker with two `(N)` spans | `# => [pad(16), foreign_procedure_inputs(15)]` |
| Variable-length remainder | trailing `, ...` |

Canonical references: `crates/miden-protocol/asm/protocol/src/tx.masm` in [protocol](https://github.com/0xMiden/protocol) for the `(N)` family in both doc blocks and inline trackers and for the `, ...` trailing-remainder form; `crates/lib/core/asm/crypto/hashes/poseidon2.masm` and `crates/lib/core/asm/stark/deep_queries.masm` in [miden-vm](https://github.com/0xMiden/miden-vm) for further `, ...` examples.

## 3. Doc comment divergences across repos

`masm-doc-comments` defines the `#!` block layout. Real source shows protocol and miden-vm use different but active variants of several sections. Document both, do not flatten.

| Dimension | protocol (dominant) | miden-vm (mixed across files) |
|---|---|---|
| Inputs/Outputs heading | Plural `Inputs:` / `Outputs:` is effectively universal (938 uses; singular `Input:` never appears). Four procs pair `Inputs:` with singular `Output:` — two in `protocol/src/tx.masm`, two in the kernel `transaction/lib/api.masm` | Singular is the *majority* here: `Input:` 144 / `Output:` 148 against `Inputs:` 107. Both are active, sometimes in the same file — `crypto/hashes/poseidon2.masm` uses each form roughly half the time |
| Panics heading | `Panics if:` with bullet list | `# Panics` markdown-style heading with prose (`mem.masm`), also `Panics if:` (`math/u128.masm`) |
| `Invocation:` line | Standard (`exec`, `call`, `dynexec`; `syscall` in kernel files) | Uneven — present in `math/u128.masm` and `crypto/hashes/sha256.masm`, absent from `blake3.masm`, `keccak256.masm` and `poseidon2.masm` |
| `Cycles:` section | Rare but present (multi-line form in `protocol/src/note.masm`) | Common but far from universal — roughly a quarter of `pub proc`s carry one, and the big `math/u64.masm`, `math/u128.masm`, `math/u256.masm` and `stark/constants.masm` modules have none at all |

Recommendation: when writing new protocol-style code (contracts, account components, tutorial MASM), follow the protocol dominant style (plural `Inputs:`/`Outputs:`, `Panics if:`, `Invocation:`). Use the `Invocation:` value that matches how the procedure is reached: `call` for public account-component / contract procedures, `exec` for internal library procedures, `dynexec` for dynamically invoked procedures. When editing inside an existing miden-vm file, match that file's local style.

Canonical references: `crates/miden-protocol/asm/protocol/src/faucet.masm` and `native_account.masm` in [protocol](https://github.com/0xMiden/protocol) for plural headings and `Invocation:`; `crates/miden-standards/asm/standards/wallets/basic.masm` in protocol for `Invocation: call` on public account-component procedures; `crates/lib/core/asm/mem.masm`, `crates/lib/core/asm/crypto/hashes/poseidon2.masm`, and `crates/lib/core/asm/math/u128.masm` in [miden-vm](https://github.com/0xMiden/miden-vm).

## 4. The `Cycles:` Section

`Cycles:` is common on public procedures in `miden-vm` and rare but present in `protocol`. Match the local file or repo style rather than applying a blanket rule. Three observed shapes:

Fixed count:

```masm
#! Cycles: 12
```

Linear expression with a named variable:

```masm
#! Cycles: <fixed> + <coef> * <var>, where `<var>` is <definition>
```

Conditional multi-line block introduced by an empty `#! Cycles:` header, followed by per-condition bullets:

```masm
#! Cycles:
#! - <condition A>: <expr A>
#! - <condition B>: <expr B>
#! where `<var>` is <definition>
```

A prose variant `Total cycles: ...` is also used in some miden-vm files.

Canonical references: `crates/lib/core/asm/crypto/hashes/poseidon2.masm` in [miden-vm](https://github.com/0xMiden/miden-vm) for all three shapes; `crates/miden-protocol/asm/protocol/src/note.masm` in [protocol](https://github.com/0xMiden/protocol) for the multi-line form outside of stdlib; `crates/lib/core/asm/mem.masm` in miden-vm for the `Total cycles:` prose variant.

## 5. Assertions and Error Messages

Two active forms:

- Named constant (dominant in protocol): `assert*.err=ERR_CONSTANT_NAME` (the `.err=ERR_*` suffix attaches to `assert`, `assert_eq`, `assertz`, etc.).
- Inline string (dominant in miden-vm): `assert.err="lowercase descriptive message"`.

Chained guard pattern, called out in `0xMiden/agent-tools#6`:

```masm
dup u32assert2 u32lte.MAX_LEAF_SIZE assert.err="invalid leaf: larger than maximum size of 8192"
```

Multiple u32 guards are chained on one line followed by a single `assert.err=` attachment. The same pattern with `u32lt` / `u32gte` and other comparators is also common.

Doc rule: `Panics if:` bullets describe the condition, not the error identifier. A bullet like `the nonce has already been incremented.` is preferred over `ERR_ACCOUNT_NONCE_CAN_ONLY_BE_INCREMENTED_ONCE.`.

Canonical references: `crates/miden-protocol/asm/protocol/src/note.masm` in [protocol](https://github.com/0xMiden/protocol) for the plain `assert.err=ERR_*` form, `crates/miden-protocol/asm/protocol/src/active_note.masm` for the `assert_eq.err=ERR_*` form, and `crates/miden-agglayer/asm/agglayer/bridge/bridge_in.masm` for both; `crates/lib/core/asm/mem.masm`, `crates/lib/core/asm/stark/random_coin.masm`, and `crates/lib/core/asm/collections/smt.masm` in [miden-vm](https://github.com/0xMiden/miden-vm) for inline string forms and the chained guard pattern.

## 6. `miden-format`, the MASM formatter

Mechanical formatting is handled by the `miden-format` binary that ships in `miden-vm` (`crates/miden-format`). Run it over paths or over stdin:

```bash
miden-format path/to/file.masm            # rewrite in place
miden-format --check path/to/dir          # exit non-zero if anything would change
miden-format --stdin --stdin-filepath a.masm < a.masm
```

When walking a directory it processes only `.masm` files.

Configuration comes from a `miden-format.toml` in the **current working directory**, with `--config` merged on top of it:

```toml
indent_width = 4              # alias: indent_size
max_line_length = 100
overflow_delimited_expr = false
```

Those three keys are the entire configuration surface, and the values above are the defaults. The formatter's README also shows a "Hypothetical future configuration" table — those options do not exist; do not put them in a `miden-format.toml`.

`miden-format` normalizes whitespace and wrapping. It does not enforce anything in this skill or its prerequisites — naming, doc-block section order, `# =>` trackers, and error-message style all remain manual review items.

## 7. Description Verbs

Doc descriptions start with a capitalized present-tense verb and end the first sentence with a period. Representative canonical verbs used in source: `Returns`, `Creates`, `Increments`, `Computes`, `Copies`, `Asserts`, `Verifies`, `Hashes`, `Adds`, `Removes`. Multi-sentence elaboration continues on following `#!` lines.

Canonical references: `crates/miden-protocol/asm/protocol/src/native_account.masm` and `asset.masm` in [protocol](https://github.com/0xMiden/protocol); `crates/lib/core/asm/mem.masm` and `crates/lib/core/asm/math/u64.masm` in [miden-vm](https://github.com/0xMiden/miden-vm).

## 8. Inline Stack Tracker Integration

`masm-inline-comments` owns the lowercase-start and comment-only-non-obvious rules. This skill adds one integration rule: an inline `# => [...]` tracker uses the exact same item names, capitalization, and `(N)` span notation as the `#!` doc block.

Synthetic illustration (not a real proc; see Canonical reference below for a real example):

```masm
#! Outputs: [final_nonce]
pub proc example
    # => [final_nonce, pad(15)]
end
```

In the illustration above, the single-felt name `final_nonce` is identical in the doc block and the inline tracker, and the `pad(15)` span follows the `(N)` family rule. The same principle holds in real source: Word-sized items are UPPERCASE in both places, and composite names like `account_id_{suffix,prefix}` decompose into their underlying felts in inline trackers (e.g. `account_id_suffix`, `account_id_prefix`).

Canonical reference: any public proc in `crates/miden-protocol/asm/protocol/src/native_account.masm` in [protocol](https://github.com/0xMiden/protocol) shows this pattern end-to-end.

## 9. Compact Before / After

A malformed protocol-style procedure followed by its corrected form. Every fix is justified by the rule it applies.

Before:

```masm
#! returns the nonce of the native account
#!
#! Input:  []
#! Output: [Final_Nonce]
#!
#! Where:
#! - Final_Nonce is the nonce of the account
pub proc get_nonce
    # Get the nonce
    push.ACCOUNT_GET_NONCE_OFFSET
    syscall.exec_kernel_proc
end
```

After:

```masm
#! Returns the nonce of the native account.
#!
#! Inputs:  []
#! Outputs: [final_nonce]
#!
#! Where:
#! - final_nonce is the nonce of the account.
#!
#! Invocation: exec
pub proc get_nonce
    # get the nonce
    push.ACCOUNT_GET_NONCE_OFFSET
    syscall.exec_kernel_proc
end
```

Fix log:

- Capitalized description verb and trailing period: §7 (Description Verbs); pattern across procs in `native_account.masm` in [protocol](https://github.com/0xMiden/protocol).
- `Input:`/`Output:` rewritten to plural `Inputs:`/`Outputs:` to match the protocol-dominant plural style: §3 (Doc Comment Divergences); pattern in `faucet.masm` in protocol.
- `Final_Nonce` rewritten to `final_nonce` (single felt is `lower_snake_case`): §1 (Capitalization).
- `Where:` sentence ends with a period: rule owned by `masm-doc-comments`.
- `Invocation: exec` line added: §3 (protocol dominant style includes `Invocation:`); `exec` is correct here because `get_nonce` is an internal library procedure, not a public account-component entry point (those use `Invocation: call`).
- Inline comment lowercased: rule owned by `masm-inline-comments`.

## Canonical References

The full set of source files referenced above, by purpose. Repos: [protocol](https://github.com/0xMiden/protocol) and [miden-vm](https://github.com/0xMiden/miden-vm).

| File | What to study |
|---|---|
| `crates/miden-protocol/asm/protocol/src/native_account.masm` (protocol) | end-to-end protocol-style proc: composite `{suffix,prefix}`, `Panics if:`, `Invocation:`, inline `pad(N)` tracking |
| `crates/miden-protocol/asm/protocol/src/faucet.masm` (protocol) | Word UPPERCASE in `Inputs:`/`Outputs:`, plural heading style |
| `crates/miden-protocol/asm/protocol/src/tx.masm` (protocol) | `(N)` span family in both doc blocks and inline trackers; also the singular `Output:` exceptions to the plural-dominant style |
| `crates/miden-standards/asm/standards/wallets/basic.masm` (protocol) | `Invocation: call` on public account-component procedures |
| `crates/miden-protocol/asm/protocol/src/active_note.masm` (protocol) | `assert_eq.err=ERR_*` / `assert_eqw.err=ERR_*` named-constant style |
| `crates/miden-protocol/asm/protocol/src/note.masm` (protocol) | plain `assert.err=ERR_*` named-constant style and multi-line `Cycles:` outside of stdlib |
| `crates/miden-protocol/asm/protocol/src/active_account.masm` (protocol) | brace-spacing variance (this module contains no assertions) |
| `crates/miden-agglayer/asm/agglayer/bridge/bridge_in.masm` (protocol) | `assert_eq.err=ERR_*` named-constant style |
| `crates/lib/core/asm/crypto/hashes/poseidon2.masm` (miden-vm) | singular `Input:`/`Output:` and all three `Cycles:` shapes |
| `crates/lib/core/asm/mem.masm` (miden-vm) | plural `Inputs:`/`Outputs:` co-existing in vm, `# Panics` heading, `Total cycles:` prose variant |
| `crates/lib/core/asm/math/u128.masm` (miden-vm) | `Invocation: exec` present in newer vm files |
| `crates/lib/core/asm/collections/smt.masm` (miden-vm) | chained `u32assert2 u32lte.<CONST> assert.err="..."` guard |
| `crates/lib/core/asm/math/u64.masm` (miden-vm) | `Asserts` description verb |
| `crates/lib/core/asm/stark/random_coin.masm` (miden-vm) | inline string `assert.err="..."` style |
