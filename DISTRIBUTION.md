# Distribution

librus-mcp is a local stdio server. It is distributed as a PyPI package, an MCP
Bundle and an MCP Registry listing that points at both. There is deliberately
no hosted or remote endpoint: it would pass Librus passwords and children's
school data through a third party.

## Channels

| Channel | What users get | Credentials |
| --- | --- | --- |
| PyPI `librus-mcp` | `uvx --python 3.14 librus-mcp==X --config FILE`, as in the README | configuration file, or `LIBRUS_USERNAME` and `LIBRUS_PASSWORD` |
| MCP Bundle `librus-mcp-X.mcpb` | one-click install in hosts that support bundles | the host's settings form (login and password marked sensitive) |
| MCP Registry `io.github.krzysztofbury/librus-mcp` | discovery and install in registry clients and aggregators | the client asks for the environment variables |

## How a release publishes them

`publish.yml` runs on a published GitHub Release:

1. `verify` checks that `server.json` and the README marker
   `<!-- mcp-name: io.github.krzysztofbury/librus-mcp -->` match the version
   (`release_verification/verify_release.py`), runs every gate, builds the
   wheel and sdist, then builds the bundle around that wheel
   (`scripts/build_mcpb.py`) and runs it as a host would
   (`release_verification/verify_mcpb.py`).
2. `publish` uploads the wheel and sdist to PyPI after `pypi` environment approval.
3. `registry` attaches the bundle to the GitHub Release, waits until PyPI serves
   the version, adds the bundle with its SHA-256 to `server.json`, and publishes
   it with a Sigstore-verified `mcp-publisher` using GitHub OIDC. No secret is
   needed: the `io.github.krzysztofbury` namespace is proven by the workflow's
   identity, and PyPI ownership by the README marker of that version.

## The bundle

`mcpb/manifest.json` uses manifest 0.4 with the `uv` server type: the host
installs Python and the dependencies with uv. The bundle contains:

- the verified wheel, installed from a path source rather than PyPI;
- a `pyproject.toml` that constrains every dependency to the version in the
  project's `uv.lock`, and a `uv.lock` resolved from it, so the host installs
  the qualified closure. The build fails if any version differs.
- `.python-version` and `requires-python = "==3.14.*"`. Without them uv picks
  the newest Python; on 3.15 the locked `pydantic-core` has no wheel and the
  install falls back to a Rust source build, which fails on a normal machine.

The bundle is not signed (`mcpb sign`); hosts show it as unsigned.

## Verified and not verified

Verified by CI and the release workflow, on Linux, macOS and Windows:
`server.json` passes `mcp-publisher validate`, the manifest passes
`mcpb validate`, and the unpacked bundle starts through its own `mcp_config`
command, serves the catalog and loads the host-provided login.

Not verified until a release or a manual check:

- the registry's PyPI ownership check and the first publish, which need a
  release whose PyPI README carries the marker;
- installation in Claude Desktop on macOS and Windows, including whether its
  uv runtime downloads Python 3.14;
- Anthropic's directory review for bundles, a manual submission per release.
  It requires a title and safety annotations on every tool: today no tool has
  a title, and 12 tools with `readOnlyHint=false` leave `destructiveHint`
  unset, which clients read as destructive.

## Directories

Aggregators such as Glama index the MCP Registry and GitHub. A
personal-account repository is claimed on Glama by signing in
with GitHub; no `glama.json` is needed.
