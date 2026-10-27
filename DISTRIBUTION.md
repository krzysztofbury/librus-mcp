# Distribution

librus-mcp always runs on a machine its user controls. It is distributed as a
PyPI package, a container image, an MCP Bundle and an MCP Registry listing that
points at all three. There is deliberately no hosted endpoint: a third party
would then hold Librus passwords and children's school data. Self-hosting over
HTTP on the user's own Docker host is supported; see README.md.

## Channels

| Channel | What users get | Credentials |
| --- | --- | --- |
| PyPI `librus-mcp` | `uvx --python 3.14 librus-mcp==X --config FILE` over stdio | configuration file, `LIBRUS_ACCOUNTS`, or `LIBRUS_USERNAME` and `LIBRUS_PASSWORD` |
| Image `ghcr.io/krzysztofbury/librus-mcp:X` | stdio by default; self-hosted HTTP with `--transport http` | the same, plus `LIBRUS_MCP_TOKEN` or `LIBRUS_MCP_TOKEN_FILE` for HTTP |
| MCP Bundle `librus-mcp-X.mcpb` | one-click install in apps that support bundles | the app's settings form (login and password marked sensitive) |
| MCP Registry `io.github.krzysztofbury/librus-mcp` | discovery and install in registry clients and aggregators | the client asks for the environment variables |

## How a release publishes them

`publish.yml` runs on a published GitHub Release:

1. `verify` checks that `server.json`, the README marker
   `<!-- mcp-name: io.github.krzysztofbury/librus-mcp -->` and the Dockerfile
   label `io.modelcontextprotocol.server.name` match the version and name
   (`release_verification/verify_release.py`), runs every gate, builds the
   wheel and sdist, then builds the bundle around that wheel
   (`scripts/build_mcpb.py`) and runs it as a host would
   (`release_verification/verify_mcpb.py`).
2. `publish` uploads the wheel and sdist to PyPI after `pypi` environment approval.
3. `image` builds the Dockerfile with the verified wheel as its `verified`
   build context, so the image installs exactly the published wheel, and runs
   `release_verification/verify_image.py` (ownership label, version, no
   excluded source, stdio with a read-only multi-login file, HTTP refusing a
   request without the token or with an unlisted Host and serving one with
   it). It then pushes amd64 and arm64 images tagged with the version, and
   `latest` when this is the newest release, pulls the pushed image and runs
   the same verification on it, and starts the arm64 image under QEMU.
4. `registry` attaches the bundle to the GitHub Release, waits until PyPI serves
   the version, adds the bundle with its SHA-256 to `server.json`, and publishes
   it with a Sigstore-verified `mcp-publisher` using GitHub OIDC. No secret is
   needed: the `io.github.krzysztofbury` namespace is proven by the workflow's
   identity, PyPI ownership by the README marker of that version and image
   ownership by its label.

### Image visibility

The registry checks image ownership by pulling the image anonymously. On the
2.3.0 release the new GitHub Container Registry package inherited this
repository's public visibility, linked through the image's
`org.opencontainers.image.source` label, and the registry listed it at once.
If the package is ever private, the `registry` job stops before attaching the
bundle or listing anything, with an error that points here. Set the package
public at `https://github.com/users/krzysztofbury/packages/container/librus-mcp/settings`
and re-run the job; attaching the bundle is idempotent.

## The image

The Dockerfile pins `python:3.14-slim` and uv by digest and installs every
dependency from `uv.lock` with hashes. Source builds (local, CI, Glama) install
the checkout; release builds install the verified wheel. `.dockerignore` is an
allowlist, so historical references, tests and local files never enter the
build context. The image runs as uid 10001, keeps state in `/data`, and carries
`io.modelcontextprotocol.server.name` for registry ownership. CI builds it and
runs `verify_image.py` on every change.

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

Verified by CI and the release workflow: `server.json` passes `mcp-publisher
validate`, the manifest passes `mcpb validate`, the unpacked bundle starts
through its own `mcp_config` command on Linux, macOS and Windows, and the image
serves stdio and HTTP as described above, on amd64 with arm64 started under
QEMU. The README Docker Compose setup was followed step by step against a
locally built image, and the HTTP test covers a proxy's bare Host name.

The 2.3.0 release passed the registry's PyPI, image and bundle ownership
checks; the listing shows all three packages.

Not verified yet, needing a manual check:

- installing the bundle in Claude Desktop on macOS and Windows, including
  whether its uv runtime downloads Python 3.14;
- Hermes Agent and other HTTP clients against the stateless, JSON-response
  transport; the MCP Python SDK client is tested;
- Anthropic's directory review for bundles, a manual submission per release.

## Directories

Aggregators such as Glama index the MCP Registry and GitHub. A personal-account
repository is claimed on Glama by signing in with GitHub; no `glama.json` is
needed.

Glama does not build this repository's Dockerfile. It generates its own image
from a build spec kept in its admin pages, which the inferred defaults got
wrong (Python 3.15 and a configuration path that does not exist). The spec
that passes its build test is:

- base image `debian:trixie-slim`, Python `3.14`;
- build steps `["uv sync --locked --no-dev"]`;
- command `["mcp-proxy", "--", "uv", "run", "--no-sync", "librus-mcp"]`;
- placeholder parameters `{"LIBRUS_USERNAME": "glama-placeholder",
  "LIBRUS_PASSWORD": "glama-placeholder"}`. Listing tools needs no Librus <!-- pragma: allowlist secret -->
  connection, so a placeholder login is enough.

Glama scores tool definitions (TDQS) per Glama release, from the built
image's catalog.
