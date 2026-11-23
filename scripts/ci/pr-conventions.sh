#!/usr/bin/env bash
# Enforces the pull request title and Type rules:
#   1. the title is BE1-<n>[-<m>]: <card title>;
#   2. the body, which becomes the squash commit body, has exactly one valid Type: line.
# This repository is on GitHub Flow and has no releases, so there are no branch or release rules.
# The title and body are data: they are only matched, never printed or executed.
# Env: PR_TITLE, PR_BODY. Exit 0: conventions kept. Exit 1: broken.
set -uo pipefail

title=${PR_TITLE:-}
body=${PR_BODY:-}

card_title='^BE1-[0-9]+(-[0-9]+)?: .+$'
failed=0

if ! [[ "${title}" =~ ${card_title} ]]; then
  echo '::error::pr-conventions: PR title must match ^BE1-[0-9]+(-[0-9]+)?: .+$'
  failed=1
fi

body=${body//$'\r'/}
types=$(printf '%s\n' "${body}" | grep -c '^Type:')
if [ "${types}" -ne 1 ]; then
  echo "::error::pr-conventions: the PR body must have exactly one Type: line (found ${types})"
  failed=1
elif ! grep -qxE 'Type: (feat|fix|chore|docs|refactor|test|ci)' <<<"${body}"; then
  echo '::error::pr-conventions: the Type: line must be one of feat, fix, chore, docs, refactor, test, ci'
  failed=1
fi

[ "${failed}" -eq 0 ] || exit 1
echo "pr-conventions: ok (title, Type line)"
