#!/usr/bin/env bash
# Configure branch protection ruleset for valg-data main branch.
# Restricts push to Mads's account only, disables force-push and deletion.
# Usage: ./scripts/setup-branch-protection.sh <owner>/<repo>

set -euo pipefail

REPO="${1:?Usage: $0 owner/repo}"

gh api "repos/${REPO}/rulesets" \
  --method POST \
  --input - <<'JSON'
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main"],
      "exclude": []
    }
  },
  "rules": [
    {"type": "non_fast_forward"},
    {"type": "deletion"}
  ]
}
JSON

echo "Ruleset created. Now add push bypass actors in GitHub UI:"
echo "  Settings > Rules > Rulesets > main-protection > Bypass actors"
echo "  Add your account as the only bypass actor for push."
