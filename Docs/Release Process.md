# Release process

Crabwalk releases are immutable, tag-driven builds. The release tag is the only
source checkout used to build public artifacts.

## One-time repository configuration

Repository administrators must configure these controls before cutting a release:

1. Create a PyPI Trusted Publisher for the `crabwalk-lang` project, this GitHub
   repository, workflow `release.yml`, and environment `pypi`.
2. Protect the `pypi` environment and restrict deployments to protected version
   tags.
3. Add a GitHub ruleset for `main` that requires pull requests and every `Crabwalk
   CI` quality/native-matrix/intermediate-Python status check.
4. Add a tag ruleset for `v*.*.*` that restricts creation and deletion to release
   maintainers.

These account-level controls cannot be expressed solely in a repository file and
must be verified in GitHub and PyPI settings.

## Cutting a release

1. Set the final version in `src/crabwalk/_version.py`, update `CHANGELOG.md`, and
   merge the release candidate after the ordinary required checks pass.
2. Create and push an annotated `vX.Y.Z` tag at that exact commit.
3. The `Crabwalk Release` workflow verifies that the tag and package version match,
   invokes the complete CI workflow, and builds the wheel and source distribution
   once.
4. The workflow validates package metadata and installs each exact artifact in clean
   Python 3.11 and 3.14 environments.
5. After all gates pass, GitHub's OIDC identity publishes the files to PyPI. The
   workflow attaches those same files and `SHA256SUMS` to the GitHub release.
6. Verify the public index with a clean, uncached install:

   ```text
   python -m pip install --no-cache-dir crabwalk-lang==X.Y.Z
   ```

7. Verify that a Crabwalk-generated application wheel resolves its runtime
   dependency normally, without `--no-deps`.
8. Move `main` immediately to the next development version.

Never rebuild a published version from a later branch state. If a release has a
defect, publish a new patch version.
