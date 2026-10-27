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
  the 128 and 144 KiB budgets in [MCP_CONTRACT.md](MCP_CONTRACT.md); output
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
- Releases follow [DISTRIBUTION.md](DISTRIBUTION.md). Bump every pinned version
  in README.md, `server.json` and the docs that name it, date the CHANGELOG
  entry, and record catalog sizes in NATIVE_TEST_PLAN.md.
- Wait on CI by run ID for the pushed commit (`gh run watch ID --exit-status`).
  While it runs, compare each job's elapsed time with its finished siblings and
  report an outlier at once instead of waiting.
- Do not claim a package, command, test or release step works until it has been
  exercised.
