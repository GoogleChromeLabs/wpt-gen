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

import os
import sys
import tempfile

# Add scripts directory to path to import check_license
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
)
from check_license import check_license, PY_LICENSE


def test_check_license_no_missing() -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        # Create a file with a license
        file_path = os.path.join(tempdir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(PY_LICENSE + '\\nprint("Hello")\\n')

        # Check license
        missing = check_license(
            fix=False, directories=[tempdir], exit_on_fail=False
        )
        assert len(missing) == 0


def test_check_license_missing() -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        # Create a file without a license
        file_path = os.path.join(tempdir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write('print("Hello")\\n')

        # Check license
        missing = check_license(
            fix=False, directories=[tempdir], exit_on_fail=False
        )
        assert len(missing) == 1
        assert missing[0] == file_path


def test_check_license_fix() -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        # Create a file without a license
        file_path = os.path.join(tempdir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write('print("Hello")\\n')

        # Fix license
        missing_before = check_license(
            fix=True, directories=[tempdir], exit_on_fail=False
        )
        assert len(missing_before) == 1
        assert missing_before[0] == file_path

        # Verify license is added
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        assert "Licensed under the Apache License" in content
        assert 'print("Hello")' in content

        # Check again
        missing_after = check_license(
            fix=False, directories=[tempdir], exit_on_fail=False
        )
        assert len(missing_after) == 0
