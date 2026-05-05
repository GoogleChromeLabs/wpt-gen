# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Script to verify that root and lib pyproject.toml files are in sync."""

import sys
from pathlib import Path
import tomllib


def main():
    root_dir = Path(__file__).parent.parent
    root_toml_path = root_dir / "pyproject.toml"
    lib_toml_path = root_dir / "lib" / "pyproject.toml"

    if not root_toml_path.exists():
        print(f"Error: Root pyproject.toml not found at {root_toml_path}")
        sys.exit(1)
    if not lib_toml_path.exists():
        print(f"Error: Lib pyproject.toml not found at {lib_toml_path}")
        sys.exit(1)

    with open(root_toml_path, "rb") as f:
        root_data = tomllib.load(f)
    with open(lib_toml_path, "rb") as f:
        lib_data = tomllib.load(f)

    # Compare dependencies (excluding google-adk from root)
    root_deps = [
        d
        for d in root_data.get("project", {}).get("dependencies", [])
        if not d.startswith("google-adk")
    ]
    lib_deps = lib_data.get("project", {}).get("dependencies", [])

    if root_deps != lib_deps:
        print("Error: Dependencies in pyproject.toml files are out of sync!")
        print(f"Root dependencies (filtered): {root_deps}")
        print(f"Lib dependencies: {lib_deps}")
        sys.exit(1)

    # Compare project metadata except expected differences
    # Readme path is different in lib (../README.md vs README.md)
    root_proj = dict(root_data.get("project", {}))
    root_proj.pop("name", None)
    root_proj.pop("dependencies", None)
    root_proj.pop("readme", None)
    root_proj.pop("description", None)
    root_proj.pop("optional-dependencies", None)
    root_proj.pop("scripts", None)
    root_proj.pop("urls", None)

    lib_proj = dict(lib_data.get("project", {}))
    lib_proj.pop("name", None)
    lib_proj.pop("dependencies", None)
    lib_proj.pop("readme", None)
    lib_proj.pop("description", None)
    lib_proj.pop("optional-dependencies", None)
    lib_proj.pop("scripts", None)
    lib_proj.pop("urls", None)

    if root_proj != lib_proj:
        print("Error: Project metadata in pyproject.toml files is out of sync!")
        import difflib
        import pprint

        root_str = pprint.pformat(root_proj).splitlines()
        lib_str = pprint.pformat(lib_proj).splitlines()

        for line in difflib.unified_diff(
            root_str, lib_str, fromfile="root_project", tofile="lib_project"
        ):
            print(line)

        sys.exit(1)

    print(
        "Success: pyproject.toml files are in sync (apart from expected differences)."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
