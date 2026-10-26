# Security

The native MIT-licensed 2.0 package uses the independent API and does not ship
the GPL-scoped historical references. Configuration files and state directories
must be private. On POSIX, the current user's own shared configuration file and
directories are restricted in place (0600/0700) through no-follow descriptors;
anything owned by another user, symlinked or special is rejected. Windows requires
local fixed NTFS and conservative ACLs, which are never repaired automatically.
1.x notification files are archived, never deleted; malformed ones are left in
place. No backend fallback or uncertain-send retry is allowed.

The self-hosted HTTP transport requires a bearer token on every request and
refuses to start without one. It has no TLS of its own: run it behind a reverse
proxy with TLS or on a private network, publish its port only on loopback or a
VPN address, and treat the token like the passwords it unlocks. The container
image runs as an unprivileged user and contains only the package and its
locked dependencies.
For consent and recovery boundaries, see [MIGRATION_2_0.md](MIGRATION_2_0.md).

## Reporting Security Issues

> Do not open issues that might have security implications!
> It is critical that security related issues are reported privately so we have time to address them before they become public knowledge.

Vulnerabilities can be reported through the repository's **Security** tab
(**Report a vulnerability**) or by emailing:

- librus-mcp [contact@datacraze.io](mailto:contact@datacraze.io)

Please include the requested information listed below (as much as you can provide) to help us better understand the nature and scope of the possible issue:

- Type of issue (e.g. credential exposure, injection, authentication bypass, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- The location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Environment (e.g. Linux / Windows / macOS)
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit the issue

This information will help us triage your report more quickly.

## Preferred Languages

We prefer all communications to be in English.

## Repository Protections

The default branch requires a pull request and the CI checks, and refuses force
pushes and deletion. Secret scanning with push protection, Dependabot alerts and
security updates, CodeQL default setup and private vulnerability reporting are
enabled. Workflows default to a read-only token and need approval before running
for outside contributors.
