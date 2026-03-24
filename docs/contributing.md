# How to Contribute

We would love to accept your patches and contributions to this project.

## Before you begin

### Sign our Contributor License Agreement

Contributions to this project must be accompanied by a
[Contributor License Agreement](https://cla.developers.google.com/about) (CLA).
You (or your employer) retain the copyright to your contribution; this simply
gives us permission to use and redistribute your contributions as part of the
project.

If you or your current employer have already signed the Google CLA (even if it
was for a different project), you probably don't need to do it again.

Visit <https://cla.developers.google.com/> to see your current agreements or to
sign a new one.

### Review our Community Guidelines

This project follows [Google's Open Source Community
Guidelines](https://opensource.google/conduct/).

## Contribution process

### Code Reviews

All submissions, including submissions by project members, require review. We
use [GitHub pull requests](https://docs.github.com/articles/about-pull-requests)
for this purpose.

## Release Process (Maintainers)

To publish a new version of `wpt-gen` to PyPI, we use GitHub Actions for automated releases.

1. Ensure all changes are merged into the `main` branch and the version number is bumped in `pyproject.toml` and `wptgen/__init__.py`.
2. Go to the **Releases** section on GitHub and click **Draft a new release**.
3. Create a new tag matching the version number (e.g., `v1.0.0`) targeting the `main` branch.
4. Fill in the release title and describe the changes (or use the auto-generate release notes feature).
5. Click **Publish release**.
6. This will automatically trigger the `.github/workflows/publish.yml` workflow, which builds the Python distribution and securely publishes it to PyPI using Trusted Publishing (OIDC).
