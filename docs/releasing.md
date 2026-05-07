# Release Process

This document describes the process for creating a new release of `wpt-gen` and publishing it to PyPI.

## Automated Releases

WPT-Gen uses GitHub Actions to automate the release process. When a new release is published on GitHub, a workflow automatically builds the package and publishes it to PyPI.

## Step-by-Step Release Guide

### 1. Prepare the Release

Before creating a release, ensure that the version number is updated in the codebase.

1.  **Update Version**: Update the version string in the following files:
    *   `pyproject.toml` (under `[project]`)
    *   `wptgen/__init__.py` (the `__version__` variable)
2.  **Run Presubmit**: Run `make presubmit` to ensure all tests pass and the code complies with project standards.
3.  **Commit and Push**: Commit the version updates and push them to the `main` branch.

### 2. Create a GitHub Release

1.  Navigate to the repository on GitHub: `https://github.com/GoogleChromeLabs/wpt-gen`.
2.  Click on **Releases** in the right sidebar.
3.  Click **Draft a new release**.
4.  **Choose a tag**: Click "Choose a tag" and type the new version (e.g., `v0.5.0`).
5.  **Target**: Ensure the target is the `main` branch.
6.  **Title**: Enter a release title (e.g., `Release 0.5.0`).
7.  **Description**: Describe the changes in this release. You can use the "Generate release notes" button to automatically pull in merged pull requests.
8.  Click **Publish release**.

### 3. Verification

After publishing the release:
1.  Go to the **Actions** tab in the GitHub repository.
2.  You should see a running workflow named "Publish to PyPI".
3.  Wait for the workflow to complete successfully.
4.  Verify that the new version is available on PyPI: `https://pypi.org/project/wpt-gen/`.

## Trusted Publishing

The GitHub Action uses **Trusted Publishing** (OIDC) to authenticate with PyPI. This means there are no PyPI tokens stored in GitHub secrets. The authentication is handled securely between GitHub and PyPI based on the repository and environment configuration.
