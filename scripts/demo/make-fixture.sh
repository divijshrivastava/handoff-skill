#!/usr/bin/env bash
#
# Builds the demo repository for the Handoff GIF.
#
# The scenario is the skill's headline claim: a stale unchecked box that a
# later commit already satisfied. Nothing here is staged for the camera --
# the commit that implements the box is real, and the ledger genuinely was
# never updated, which is why the audit has something true to find.
#
#   ./make-fixture.sh [target-dir]     (default: /tmp/handoff-demo)
#
set -euo pipefail

TARGET="${1:-/tmp/handoff-demo}"

if [ -e "$TARGET" ]; then
  echo "refusing to overwrite existing $TARGET -- remove it first" >&2
  exit 1
fi

mkdir -p "$TARGET"
cd "$TARGET"
git init -q
git config user.name "agent-a"
git config user.email "agent-a@example.com"
git config commit.gpgsign false

# ---------------------------------------------------------------- commit 1
# Filtering exists. Empty-query and no-result behavior does not.

cat > search.py <<'PY'
"""Item search for the catalogue."""


def filter_items(items, query):
    """Return items whose name contains `query`."""
    return [item for item in items if query in item["name"]]
PY

cat > HANDOFF.md <<'MD'
# Handoff

## 2026-09-02 - Add search filtering (owner: agent-a)

State:

- [x] In progress
- [ ] Completed

Steps:

- [x] Implement search filtering (`search.py`).
- [ ] Verify empty queries and no-result behavior.
- [ ] Record verification and the next action.

Status: In progress. Filtering exists; edge-case verification remains.
MD

git add -A
GIT_AUTHOR_DATE="2026-09-02T14:10:00" GIT_COMMITTER_DATE="2026-09-02T14:10:00" \
  git commit -q -m "Add search filtering"

# ---------------------------------------------------------------- commit 2
# A later session implements and tests exactly what the open box asks for,
# and -- as actually happens -- never goes back to tick the box.

cat > search.py <<'PY'
"""Item search for the catalogue."""


def filter_items(items, query):
    """Return items whose name contains `query`.

    An empty query is not a filter: it returns the full list. A query that
    matches nothing returns an empty list rather than raising.
    """
    if not query:
        return list(items)
    return [item for item in items if query in item["name"]]
PY

cat > test_search.py <<'PY'
import unittest

from search import filter_items

ITEMS = [{"name": "rook"}, {"name": "bishop"}, {"name": "knight"}]


class FilterItemsTest(unittest.TestCase):
    def test_empty_query_returns_all_items(self):
        self.assertEqual(filter_items(ITEMS, ""), ITEMS)

    def test_no_match_returns_empty_list(self):
        self.assertEqual(filter_items(ITEMS, "queen"), [])

    def test_substring_match(self):
        self.assertEqual(filter_items(ITEMS, "ook"), [{"name": "rook"}])


if __name__ == "__main__":
    unittest.main()
PY

git add -A
GIT_AUTHOR_DATE="2026-09-04T09:30:00" GIT_COMMITTER_DATE="2026-09-04T09:30:00" \
  git commit -q -m "Handle empty queries and the no-result case"

echo "fixture ready: $TARGET"
echo
git --no-pager log --oneline
echo
echo "open box in HANDOFF.md:  'Verify empty queries and no-result behavior.'"
echo "already satisfied by:    $(git rev-parse --short HEAD)  test_search.py"
