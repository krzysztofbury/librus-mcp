# Native 2.0 license and provenance review

Review date: 2026-10-05. Scope: the `2.0.0.dev1` native wheel and sdist, not a
retroactive license change to any published artifact. The owner requested MIT for
their new 2.0 work. This is an engineering inventory, not legal advice or a claim
that every dependency is itself MIT.

## Source inventory and disposition

| Retained material | Origin and treatment |
| --- | --- |
| `src/librus_mcp/*.py`, `py.typed` | New consumer implementation on the native migration branch. Public API contracts supply types and behavior; no apix code, parser, fixture, private codec or SQL was transferred. MIT. |
| `tests_native/*.py` | Independently authored synthetic loopback HTTP/HTML/JSON and MCP/CLI tests. No captures or test files copied from another client or the API repository. MIT. |
| `scripts/qualify_native.py` | New explicit bounded qualifier. No credentials or account data included. MIT. |
| `scripts/run_mutations.py`, `mutation/native-baseline.json` | New checkout-only mutation runner and synthetic generated evidence, with reviewed diffs. No third-party implementation copied. MIT; excluded from wheel/sdist. Test-only mutmut integration is part of `tests_native/`, never packaged in the wheel. |
| `release_verification/` | Project-owned packaging/release helpers, updated for the native namespace and installed acceptance. Git author/contributor review identified only the project owner. Relicensed with the owner's authorization, not on authorship evidence alone. MIT. |
| Root documentation, configuration, workflow files | Project-owned documentation and configuration, including rewritten current README/SPEC/contracts. Historical changelog statements remain historical. Standard license text and public dependency/action references retain their meaning. MIT unless explicitly scoped otherwise. |
| `legacy_reference/` | Original 1.x source, tests, fixtures, docs, example and mutation configuration preserved under the original GPL-3.0-only license. Excluded from every 2.0 build inventory. No relicensing or runtime fallback. |

The root originally used MIT, then switched to GPL-3.0-only in `1a59c56` because
apix's distributed license contradicted its MIT package metadata. Retaining a
dependency name or interoperable contract is not a transfer of its implementation.
The old GPL license is preserved in `legacy_reference/LICENSE`. Historical tags,
licenses and release files are unchanged. The root MIT notice retains the original
owner's 2026 copyright attribution.

## Locked runtime dependency inventory

Derived from the runtime dependency closure in `uv.lock`, including activated
extras (`PyJWT[crypto]`) and platform markers, not the development group.
Cross-checked against the fresh installed-wheel resolver. Installed Linux metadata and license/notice
files were inspected; platform-only package metadata was retrieved from PyPI.
Dependencies are installed as separate upstream distributions, not vendored in
the MCP wheel or sdist.

| Distribution | Locked version | Published license |
| --- | --- | --- |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT, including llhttp notice |
| aiosignal | 1.4.0 | Apache-2.0 |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.14.2 | MIT |
| attrs | 26.1.0 | MIT |
| cffi | 2.1.1 | MIT-0; external libffi retains its own MIT notice |
| click | 8.5.0 | BSD-3-Clause |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause; bundled OpenSSL retains Apache-2.0 terms |
| frozenlist | 1.8.0 | Apache-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore2 | 2.12.0 | BSD-3-Clause |
| httpx2 | 2.12.0 | BSD-3-Clause |
| httpx2-jsfetch | 1.0 | BSD-3-Clause, conditional browser runtime |
| idna | 3.19 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| librus-python-api | 1.6.0 | MIT |
| lxml | 6.1.2 | BSD-3-Clause with additional terms below |
| mcp | 2.1.1 | MIT |
| mcp-types | 2.1.1 | MIT |
| multidict | 6.7.1 | Apache-2.0 |
| opentelemetry-api | 1.44.0 | Apache-2.0 |
| propcache | 0.5.2 | Apache-2.0, separate NOTICE retained by upstream distribution |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic-core | 2.46.5 | MIT |
| PyJWT | 2.13.0 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| pywin32 | 312 | PSF, Windows only |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.6.3 | MIT |
| sse-starlette | 3.4.8 | BSD-3-Clause |
| starlette | 1.6.0 | BSD-3-Clause |
| truststore | 0.10.4 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| tzdata | 2026.5 | Apache-2.0, timezone data includes public-domain material |
| uvicorn | 0.52.4 | BSD-3-Clause |
| yarl | 1.24.5 | Apache-2.0 |

### API dependency refresh, 2026-10-09

The API pin advances from 1.0.2 to the published 1.6.0. The installed wheel's
MIT license and metadata were inspected. Its runtime requirements are unchanged,
and the lock update changes only this package and its reviewed quarantine
exception. The API's original implementation remains separately installed;
no library parser or fixture was copied into MCP. New consumer receipt markup
and module-unavailable wire cases are independently authored synthetic inputs.
The 2.1 projections use public native model/service contracts. New history,
formative and mailbox-discovery fixtures in `tests_native/` use invented data
authored from contract requirements; no live page dump, API test fixture or
third-party parser is included. There are no new runtime dependencies beyond
the reviewed API version change.

### lxml is not wholly BSD-only

`lxml`'s `LICENSE.txt` and `LICENSES.txt` also describe ElementTree/PSF code,
separately licensed Schematron resources and a GPL test runner. Its binary wheels
can bundle zlib (zlib license), iconv (LGPL-2.1), libxml2, libxslt and libexslt
(MIT). Some schema-transformation resources are described as unlicensed in the
upstream notice. This application uses lxml through the independent API for HTML
parsing; it does not copy or invoke those test/schema resources, redistribute a
modified lxml binary, or claim their contents under its own MIT grant.

LGPL library use does not require relicensing this independent Python consumer
under GPL. Upstream distributions keep their license files. Anyone bundling the
whole installed environment or modifying/repackaging these dependencies must
review their additional notices, LGPL source/relinking obligations and resource
terms separately. This review approves the independent MCP distributions and
ordinary separate dependency installation, not an all-MIT standalone bundle.

## Optional mutation tooling, 2026-10-06

The optional POSIX `mutation` group adds separate development distributions,
not runtime dependencies or vendored source. Installed metadata/license files
were reviewed for the newly locked packages:

| Distribution | Version | Published terms |
| --- | --- | --- |
| mutmut | 3.7.0 | BSD-3-Clause |
| coverage | 7.16.0 | Apache-2.0 |
| libcst | 1.9.0 | MIT with PSF-derived parser/tokenizer files and Apache-2.0 `_add_slots.py` |
| linkify-it-py | 2.2.0 | MIT |
| mdit-py-plugins | 0.6.1 | MIT |
| platformdirs | 4.11.5 | MIT |
| setproctitle | 1.3.7 | BSD-3-Clause |
| textual | 8.2.8 | MIT |

Existing development/runtime dependencies remain separately installed with their
upstream notices. The additional mutation guide is shipped in the sdist, but
generated campaign reports and the checkout-only runner remain outside artifacts.
Nothing in this update relicenses or bundles the tooling under MCP's MIT grant.
The secret scanner's 39 new high-entropy findings were individually matched to
the actual public source/test/tooling SHA256 fingerprints in the reviewed report.
Only those exact findings were added as false positives; all existing entries
and scanner filters remain unchanged.

## Artifact and maintenance gates

The whole tracked-tree secret scan was reviewed: its outstanding historical
findings were synthetic test passwords and public uv artifact checksums, not
deployment secrets. Exact synthetic values are individually baselined without
excluding the legacy tree from scanning; public checksums carry inline reasons.
No broad new secret filter was added. Historical reference contents remain intact.

- The wheel includes only `librus_mcp` and distribution metadata/license.
- The sdist uses an explicit allowlist, excluding `legacy_reference`, legacy
  tooling, captures, credentials and generated mutation/build data.
- The installed verifier checks native entry/identity, apix absence and typed
  feature catalogs. Artifact license/inventory checks reject an accidentally
  retained GPL license or historical source in the native distribution.
- No third-party GPL-only implementation is included in the new wheel/sdist.
  The separate historical reference directory keeps its GPL terms.
- Refresh this review when runtime dependency versions, vendored material or
  build inventories change. Do not infer license approval from metadata alone.
