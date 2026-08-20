#!/usr/bin/env bash
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

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <PR_NUMBER> <BUILD_ID> [PROJECT] [REGION]"
  echo ""
  echo "Example:"
  echo "  $0 552 3c7292ad-a8a8-4723-8c28-495ec3e15fcd"
  exit 1
fi

PR_NUMBER="$1"
BUILD_ID="$2"
PROJECT="${3:-interop-tooling-ops}"
REGION="${4:-us-central1}"

echo "==> Fetching Cloud Build log for ${BUILD_ID} (${PROJECT}/${REGION})..."
GIST_URL=$(gcloud builds log "${BUILD_ID}" --project "${PROJECT}" --region "${REGION}" | \
  gh gist create -d "Cloud Build Logs: ${BUILD_ID} (PR #${PR_NUMBER})" -f "build-${BUILD_ID}.log" -)

echo "==> Gist created: ${GIST_URL}"
echo "==> Posting link as comment to PR #${PR_NUMBER}..."

gh pr comment "${PR_NUMBER}" --body "### 📋 Cloud Build Execution Logs for \`${BUILD_ID}\`

Full execution logs have been uploaded for review:
🔗 **[build-${BUILD_ID}.log](${GIST_URL})**"

echo "==> Successfully posted logs to PR #${PR_NUMBER}!"
