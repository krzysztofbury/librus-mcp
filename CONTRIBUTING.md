# Contributing to librus-mcp

Thank you for your interest in contributing! This document provides guidelines to make the process smooth for everyone.

## Getting Started

1. Fork the repository
2. Clone your fork and set up the development environment:
    ```bash
    git clone https://github.com/YOUR_USERNAME/librus-mcp.git
    cd librus-mcp
    uv sync --locked --python 3.14
    ```
3. Create a branch for your change:
    ```bash
    git checkout -b your-branch-name
    ```

## Development Workflow

### Code Style

The key rules:

- **Safety first:** Validate inputs and outputs with assertions (~2 per function)
- **Split assertions:** `assert a; assert b` - never `assert a and b`
- **Functions <= 70 lines**
- **No abbreviations** in variable names
- **Comments explain "why"**, not "what"
- **Lines <= 100 columns**

### Linting and Formatting

Before submitting, run the same checks as CI:

```bash
uv lock --check
uv sync --locked --python 3.14
uv run ruff check src/librus_mcp/ tests_native/ release_verification/ scripts/
uv run ruff format --check src/librus_mcp/ tests_native/ release_verification/ scripts/
uv run bandit -c pyproject.toml -r src/librus_mcp/
uv run mypy
uv run pytest -q
uv build --no-build-isolation
```

To apply formatting before rerunning the format check:

```bash
uv run ruff format src/librus_mcp/ tests_native/ release_verification/ scripts/
```

### Testing

The active `tests_native/` suite is offline and uses original synthetic loopback
HTTP through real MCP stdio and the pinned API. `legacy_reference/tests/` remains an unshipped 1.x
reference; it imports the removed apix backend and is not native CI evidence.
See [verification ownership](NATIVE_TEST_PLAN.md). Do not restore apix as a dev
dependency to run old tests. Port consumer invariants, not private wrapper mocks.

Do not run `legacy_reference/verify_connection.py` on this branch. Native live
qualification uses `scripts/qualify_native.py` and requires explicit approval and bounded
operation scope. Ordinary CI never uses school credentials.
The `--phase v21` profile covers new 2.1 summary/history/discovery operations and
bounded continuation, with optional stores and body opens disabled. See
[verification ownership](NATIVE_TEST_PLAN.md) for budgets and reporting limits.

### Mutation Testing

The native campaign uses the optional locked mutmut 3 group and exercises
MCP-owned safety boundaries through real stdio children. Run instructions,
instrumentation proof, exact scope and reviewed survivors are in
[MUTATION_TESTING.md](MUTATION_TESTING.md). Do not run mutmut directly in the
checkout; the script owns disposable copies and cleanup. No mutation-score
target is a release gate.

## Submitting Changes

1. Commit your changes with a clear, descriptive message
2. Push to your fork
3. Open a Pull Request against `main`
4. Describe what your change does and why

### What Makes a Good PR

- **Focused:** One logical change per PR
- **Documented:** Update README.md if you add/change tools
- **Linted:** All ruff checks pass with zero warnings
- **Tested:** You have verified the change works

## Adding a New MCP Tool

See [SPEC.md](SPEC.md) for ownership and [MCP_CONTRACT.md](MCP_CONTRACT.md) for wire contracts.

## Reporting Bugs

Open a GitHub issue with:

- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS

## Security Issues

**Do not open public issues for security vulnerabilities.** See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## License

Native 2.0 contributions are MIT. Unshipped 1.x references retain GPL-3.0-only.
Do not copy GPL client implementations or external fixtures into the native
package. See [LICENSE_REVIEW.md](LICENSE_REVIEW.md) before changing dependencies
or artifact inventories. Historical release licenses remain unchanged.

## Questions?

Open a GitHub issue or reach out at [contact@datacraze.io](mailto:contact@datacraze.io).
