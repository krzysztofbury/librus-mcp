# Native mutation testing

## Scope and runner

The optional `mutation` dependency group pins **mutmut 3.7.0**. The project
quarantine excludes 3.8.0; the lock uses LibCST 1.9.0 and Python 3.14. Mutmut's
fork-based runner is POSIX-only, not a Windows runtime or test requirement.
Cosmic Ray remains historical evidence in `legacy_reference/mutation/`; neither
it nor mutmut is a runtime dependency.
The campaign script and reviewed generated evidence are checkout-only tooling,
excluded from wheel/sdist inventories. Ordinary platform CI does not install the
optional group or run this campaign; its native consumer tests remain mandatory.

`scripts/run_mutations.py` runs three MCP-owned presentation/binding functions:

- `presentation.validate_window_cursor`: query/context rejection before I/O.
- `presentation.window_page`: source-change/end-offset rejection and bounded pages.
- `message_tools.require_binding`: account/context/backend binding before body reads.

The two configured pytest files use actual MCP stdio, the installed native API
and original loopback HTTP. They do not mock these production functions. Mutmut
generates 440 candidates in two modules but this focused campaign selects **70**;
the other 370 are not qualified by this campaign. Native transport, parser and
durable transaction mutation coverage belongs upstream. Consent, send uncertainty,
resources and migration still have their separate consumer integration proof.
This is not a full native-package mutation campaign or a mutation-score release gate.

Run from a repository checkout after installing the optional group:

```bash
uv sync --locked --group mutation
uv run --group mutation python scripts/run_mutations.py \
  --check-baseline mutation/native-baseline.json \
  --report mutation/latest.json
```

Set `TMPDIR` to a private scratch root when a controlled location is needed.
The script copies only source/tests/config into its own temporary directory,
clears Librus credential selectors and directs child temporary files there.
An invocation-owned `AGENT_SCRATCH_DIR` delegates cleanup to its shell wrapper:
descendants stay in that wrapper's process group, which must wait before deletion.
Standalone runs stop their runner group before temporary-directory cleanup.
SIGKILL and machine crashes cannot guarantee cleanup.
`--report` is an explicit retained deliverable, not an approval of survivors.
Do not pass the reviewed baseline as the report destination. No credentials or
production state are used. Reports retain source/test/tooling hashes and diffs.

## Subprocess instrumentation

Mutmut normally collects hits only in its pytest process. Its modified Python
import path does not reach a new `python -c` stdio server, and child hits do not
automatically enter its per-test map. Without both bridges, an E2E campaign can
silently test the original editable installation or report "no tests".

Test-only support in `tests_native/mutation_support.py` sets the child's
`PYTHONPATH` to the instrumented package and preserves `MUTANT_UNDER_TEST`.
During statistics collection, the child's normal exit writes actual trampoline
hits to the test's private report directory. `tests_native/conftest.py` merges
these hits before mutmut's teardown collector and fails if reports are absent.
Clean-test and forced-failure checks then run through the same subprocess path.
The bridge uses private mutmut statistics intentionally, with an exact version
pin; it adds no production flag, import, wrapper or instrumentation hook.

## Reviewed baseline, 2026-10-06

This retained report predates API 1.6.0 and the 2.1 message/filter and grade
projections. Changed source/test fingerprints mean it is historical evidence,
not a current 2.1 mutation qualification. Review a fresh campaign before replacing
the baseline; the ordinary offline/installed suites remain release gates.

On Linux/Python 3.14.7, **62 killed, 8 survived**, with no unchecked/no-test,
timeout or suspicious selected outcomes. All eight message-binding mutants were
killed. The first run was 58 killed/12 survived. Four genuine consumer gaps were
closed in existing owner tests, without adding parallel private-helper tests:

- Consent-enabled body reads reject independently changed account and context
  before any HTTP; without consent, a weakened binding could still be rejected
  by the separate consent guard and pass the negative assertion.
- A cursor exactly at the source end returns `STALE_CURSOR`, not an empty page.
- The public pagination `truncated`/`reason` fields match first and final pages.

The retained `mutation/native-baseline.json` contains every selected result,
source fingerprints and complete survivor diffs. Suffixes below are mutmut IDs,
not stable identifiers across function/tool changes:

| Function and suffix | Review |
| --- | --- |
| `validate_window_cursor`: 4, 6, 7 | Change the opaque query digest's serialization spelling, consistently for creation and validation. Query/context mismatch and valid continuation still work. No test freezes a particular digest spelling or promises cross-version cursor reuse. Not byte-equivalent digests. |
| `validate_window_cursor`: 8 | Changes the JSON key/value delimiter. The query is a tuple of strings, not a mapping; this delimiter has no effect. |
| `window_page`: 2 | `TypeAdapter(None).dump_json` still serializes these validated native records identically. Continuation and changed-source proof remain intact. This is an observed equivalence for the typed runtime path, not proof for arbitrary Python objects. |
| `window_page`: 7 | Skips the first cursor validation but retains the immediately following context/query check. Public rejection remains protected. |
| `window_page`: 16, 19 | Weaken/change that redundant second check; the first validation already rejects independently wrong query/context. No isolated test is added for an unreachable error branch. |

`--check-baseline` rejects changed candidate sets, tool/target changes and new or
changed survivor diffs, while allowing previously reviewed survivors to be killed.
It does not accept equal counts as equivalent evidence. When code, fixtures or
mutmut change, inspect the fresh diffs and failure reasons before replacing the
baseline. Review production invariants, not a desired score, and never copy API
parser/storage tests into MCP to inflate coverage.
