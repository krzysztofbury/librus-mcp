# Contributing to librus-mcp

Thank you for your interest in contributing! This document provides guidelines to make the process smooth for everyone.

## Getting Started

1. Fork the repository
2. Clone your fork and set up the development environment:
    ```bash
    git clone https://github.com/YOUR_USERNAME/librus-mcp.git
    cd librus-mcp
    uv venv && uv pip install -e .
    ```
3. Create a branch for your change:
    ```bash
    git checkout -b your-branch-name
    ```

## Development Workflow

### Code Style

The key rules:

- **Safety first:** Validate inputs and outputs with assertions (~2 per function)
- **Split assertions:** `assert a; assert b` — never `assert a and b`
- **Functions <= 70 lines**
- **No abbreviations** in variable names
- **Comments explain "why"**, not "what"
- **Lines <= 100 columns**

### Linting and Formatting

Before submitting, ensure your code passes:

```bash
uvx ruff check src/
uvx ruff format src/
```

### Testing

Run the verification script to confirm basic connectivity works:

```bash
python verify_connection.py
```

When adding new functionality, ensure you test it manually against a real Librus account.

### Mutation Testing

Run the focused authentication campaign:

```bash
rm -f cosmic-ray-auth.sqlite
uv run cosmic-ray init cosmic-ray-auth.toml cosmic-ray-auth.sqlite
uv run cr-filter-lines --config cosmic-ray-auth.toml cosmic-ray-auth.sqlite
uv run cr-filter-operators cosmic-ray-auth.sqlite cosmic-ray-auth.toml
uv run cosmic-ray exec cosmic-ray-auth.toml cosmic-ray-auth.sqlite
uv run cosmic-ray dump cosmic-ray-auth.sqlite
```

For the configuration and local-state campaigns, use the same commands with
`auth` replaced by `config` or `state`. The filter steps are required:
`cosmic-ray init` records all candidates before the focused line and operator
filters narrow the session.

The v1.2.2 baseline produced this evidence:

- Authentication: 114 of 140 selected mutants killed. All 41 control-flow and
  state-transition mutants in the new operation-denial path were killed. Its
  two survivors only change the rounded seconds displayed in the cooldown error.
- Local state: 120 of 173 selected mutants killed. Targeted schema, size-bound,
  nested-directory, content-identity, digest-check, and migration-direction
  mutants were all killed. Remaining survivors are equivalent mutations,
  diagnostic-only changes, exception substitutions on race paths, or branches
  for the non-host Windows locking implementation.

The v1.2.3 safety campaigns additionally killed 113 of 150 selected configuration
mutants and 157 of 224 selected local-state mutants. Surviving mutations were
manually triaged as equivalent comparisons, descriptor edge cases unavailable to
normal process startup, race-only exception substitutions, or non-host platform
branches.

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

See [SPEC.md](SPEC.md) for the step-by-step process of adding a new tool.

## Reporting Bugs

Open a GitHub issue with:

- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS

## Security Issues

**Do not open public issues for security vulnerabilities.** See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## Questions?

Open a GitHub issue or reach out at [contact@datacraze.io](mailto:contact@datacraze.io).
