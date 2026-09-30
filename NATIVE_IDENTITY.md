# Local native identity experiment

This branch adds an explicit, programmatic adapter for `get_student_information`
using a locally installed `librus-python-api` artifact. It is not a production
backend migration or a published consumer release. Default startup and every
other tool retain the existing backend. The native package is not a required
dependency until publication and full replacement qualification.

The launcher owns one `LibrusService` async context and passes it to
`NativeIdentityBackend`. Call
`LibrusManager.set_identity_backend(NativeIdentityBackend(service))` before
starting MCP, then restore `None` on shutdown. This slice bypasses the old
identity retry/session path entirely. Never copy cookies between implementations
or retry native failures through the legacy implementation.

The adapter explicitly maps immutable domain fields to the existing consumer
profile dataclass. A missing lucky-number value produces a typed native
unavailable failure rather than inventing a legacy string marker. Existing tool
names, annotations, input/output schemas, and text/structured serialization
remain unchanged. This limitation and live authentication/HTML layout gaps must
be resolved before production selection.

Offline installed-artifact stdio qualification is provided by
the library's opt-in `tests/integration/test_mcp_identity.py`, using original
synthetic loopback fixtures. Select it with pytest's `-m integration` and supply
`--mcp-checkout=/path/to/librus-mcp` from an installed-library environment; see the
library's CONTRIBUTING.md for the full command. It does not call Librus or read
production credentials. PyPI publication
is deferred until the library's `1.0.0rc1`; no production dependency pin or default
CLI switch is introduced here.
