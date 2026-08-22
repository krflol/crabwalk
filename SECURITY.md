# Security Policy

## Supported versions

Security fixes are provided for the latest Crabwalk release line. Users should
upgrade to the newest patch release before reporting a suspected vulnerability.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through the repository's
[GitHub security-advisory form](https://github.com/krflol/crabwalk/security/advisories/new).
Do not open a public issue for an undisclosed vulnerability.

Include the affected Crabwalk version, operating system, Python and Rust versions,
a minimal reproducer, and the expected impact when possible. The maintainer will
acknowledge the report, investigate it, and coordinate disclosure and a patched or
yanked release as appropriate. No fixed response-time guarantee is currently
offered.

Crabwalk executes Cargo, Rust build scripts, procedural macros, and generated native
code with the invoking developer's permissions. That documented trust boundary is
not itself a vulnerability; unexpected escapes from Crabwalk's stated compiler,
cache, wheel, ownership, panic, or native-safety invariants are in scope.
