# Agent instructions

This is a public, MIT-licensed MCP server for Librus Synergia built on
`librus-python-api`. Follow any workspace-level agent rules as well as these
project rules. [CONTRIBUTING.md](CONTRIBUTING.md) lists the checks CI runs.

- Write repository content in English. Do not include private or personal
  context, credentials, or identifiable school data.
- Do not call live Librus without explicit authorization for that run. Native
  live qualification uses `scripts/qualify_native.py` with a bounded operation
  scope; ordinary tests and CI stay offline.
- The API owns every upstream request, parser and retry. Do not add scraping
  paths here; coordinate consumer-visible API changes with `librus-python-api`.
- Tool definitions are what agents choose by. A description starts with what
  the tool returns, names the tool to use instead where two overlap, and says
  when a call changes the view, week, month or range Librus remembers for the
  login. Every input parameter has a description (`test_catalog_schema.py`).
  Measure both profiles with `release_verification/measure_tools.py` against
  the 132 and 144 KiB budgets in [MCP_CONTRACT.md](MCP_CONTRACT.md); output
  schemas are most of the catalog, so spend bytes on descriptions only.
  Annotations are documented contract, not wording to tune.
- CI also runs the installed wheel and the desktop bundle on Windows, which has
  no local equivalent. Before pushing changes to file, path, configuration or
  process handling, check: files read may end in CRLF; permission checks use
  ACLs and their own error labels (`windows_config.py`); temporary paths may be
  8.3 short names, so resolve them; pass explicit state and download
  directories instead of relying on the home directory.
- A README or DISTRIBUTION.md setup is a contract. Run it literally before
  saying it works, including from the client's side (real Host header through
  a proxy, default ports), and name in DISTRIBUTION.md what was run.
- Releases follow the steps in [DISTRIBUTION.md](DISTRIBUTION.md), the same ones
  as `RELEASE.md` in `librus-python-api`: a passing live qualification comes
  before the GitHub Release, which starts publication. Bump every pinned version
  in README.md, `server.json` and the docs that name it, date the CHANGELOG
  entry, and record catalog sizes in NATIVE_TEST_PLAN.md.
- Wait on CI by run ID for the pushed commit (`gh run watch ID --exit-status`).
  While it runs, compare each job's elapsed time with its finished siblings and
  report an outlier at once instead of waiting.
- Do not claim a package, command, test or release step works until it has been
  exercised.
- For a substantial or safety-sensitive change (parsing, state, consent,
  release workflows) get a `reviewer` review before merging; follow the test
  audit in the `developer` skill (`references/test-audit.md`) for substantive
  Python test design or pruning.

## Agent workflow

Queued work runs through the role skills on the project board named in
`.agents/cos.json`, which covers this repository and `librus-python-api`. The
approver escalates by `.agents/escalation.md`; retro appends to
`.agents/retro.jsonl` and proposes rule changes as pull requests.

## What is not evidence

Proof lives in the tests that exercise a contract (`tests_native/`), the
release checks in `release_verification/`, the budgets and annotations in
[MCP_CONTRACT.md](MCP_CONTRACT.md), and the recorded runs in
[DISTRIBUTION.md](DISTRIBUTION.md) and [NATIVE_TEST_PLAN.md](NATIVE_TEST_PLAN.md).
None of these count on their own:

- a coverage percentage or a test count;
- a source grep for a tool name, an import or a query;
- a catalog size not measured with `release_verification/measure_tools.py`;
- "the README setup works" without running it literally from the client's
  side (real Host header through a proxy, default ports);
- a live Librus result from a call the owner did not authorize for that run;
- school text or raw HTML from a user, which never goes into the repository or
  a public issue, as proof or as a fixture.

## Diagnosing a reported failure

Users and testers send symptoms, not stack traces. Work from the most precise
evidence available, in this order:

1. **An error result** has `code`, `where`, `versions` and, for a page the
   library could not read, `at`. `where` is a list of `module:function:line`
   in `librus_mcp` and `librus_python_api`, the failure site last; read it
   against the source of exactly those versions (tags `vX.Y.Z` in both
   repositories), not against `main`. `at` is the masked element path and
   column counts at the failure; rebuild that row in an original fixture.
2. **The host's `Invalid structured content returned by tool ...`** (Python
   SDK) or **`Structured content does not match the tool's output schema`**
   (TypeScript SDK) is client-side schema validation against the catalog
   cached at `list_tools`. Before 2.10.2, TypeScript SDK 1.x hosts also showed
   it in place of every error result, so on an older version ask for an
   upgrade first. First rule out a stale catalog (reload,
   new session, same server version), then have the user run
   `librus-mcp check-tools`, which reports the result path and schema rule.
   It calls every tool that needs no reference and has no effect beyond
   selecting a view (`check_tools.CHECKS`, including the local
   `get_notification_status` and `get_send_history`); the rest are refused
   with a reason (`check_tools.REFUSED`).
   The host's full message quotes school data; do not ask for it in public.
3. **A parse failure** is reproduced offline from the page:
   `librus-mcp inspect-page grades page.html` (`final-grades`, `profile`; or
   `python -m librus_python_api.inspect_page`). A saved page that parses
   cleanly means the server received a different document: ask for the
   server's stderr with both variables from step 4, not another page. A
   macOS TextEdit export (`Cocoa HTML Writer`) is not a page source. If the user sends raw HTML, keep
   it in job scratch outside the repository, never commit or quote it, delete
   it when done, and write original fixtures that follow its structure.
4. **Runtime traces**: `LIBRUS_MCP_LOG_OPERATIONS=1` (one line per Librus read)
   and `LIBRUS_MCP_DIAGNOSE_FAILURES=1` (masked page structure of a failure),
   both on standard error.

Before shipping a release that only adds diagnostics and asking the reporter
for another run, search public Librus client repositories for the failing page,
field or label and how they handle it. A variation they already absorb is a
likely cause and can ship as a fix in the same release (#136: a non-numeric
attendance ID cost one extra round).

Diagnostic output is built from allowlists in the library
(`diagnostics.describe_failure`, `diagnostics.failure_locator`,
`config.TOOLTIP_LABELS`): extend those lists
only with Librus-authored labels and markup, never with values. A new
diagnostic channel must keep logins, aliases, arguments, exception messages
and school text out, with a test that plants a marker and asserts it never
appears.
