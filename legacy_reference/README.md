# Unshipped 1.x references

This directory preserves the apix-backed source, tests and documentation for
invariant and provenance review. It is not packaged, imported, run by native CI,
or a compatibility backend. Files here retain **GPL-3.0-only** under [LICENSE](LICENSE).
They have not been relicensed as MIT. Snapshot documentation can contain stale
development notes; use the current root documentation for 2.0.

For an executable historical baseline, use the separately versioned
[v1.7.0 tree](https://github.com/krzysztofbury/librus-mcp/tree/v1.7.0) with its original
dependency lock and license. Do not add apix to the native development environment.
The [native proof-owner map](../NATIVE_TEST_PLAN.md) records the replacement
boundaries. No old tests or fixtures were copied into the native test suite.
