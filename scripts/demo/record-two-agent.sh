#!/usr/bin/env bash
# Live terminal script for the two-agent demo recording.
set -euo pipefail

export GIT_PAGER=cat
export PS1='$ '
GUARD="/Users/divij/code/handoff-skill/skills/handoff/scripts/handoff_guard.py"
TODAY="$(date +%Y-%m-%d)"

sleep 0.7
echo '# agent A picks up the task'
sleep 1.0
cat HANDOFF.md
sleep 3.5

echo
echo '# agent A implements the open step'
sleep 1.2

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

python3 -m unittest discover -q
git add search.py test_search.py
git commit -q -m "Handle empty queries and the no-result case"
A_SHA="$(git rev-parse --short HEAD)"
sleep 2.0

echo
echo "# A's session ends here. mid-task."
sleep 1.2
git --no-pager log --oneline -1
sleep 2.5

printf '\033[2J\033[H'
echo '# new session. no memory of anything above.'
sleep 2.0

echo
echo '# agent B audits and finishes'
sleep 1.2

python3 -m unittest discover -q
sleep 1.0
git --no-pager log --oneline -2
sleep 1.5

echo
echo "Open: Verify empty queries (owner: agent-a)."
echo "Already implemented in ${A_SHA} — running tests, not redoing that commit."
echo "Remaining: record verification and close the ledger entry."
sleep 3.0

python3 "$GUARD" read --root . >/tmp/handoff-read.json
VERSION="$(python3 -c 'import json; print(json.load(open("/tmp/handoff-read.json"))["version"])')"

python3 -c "
from pathlib import Path
a_sha = '${A_SHA}'
today = '${TODAY}'
text = Path('HANDOFF.md').read_text()
old = '''## 2026-09-02 - Add search filtering (owner: agent-a)

State:

- [x] In progress
- [ ] Completed

Steps:

- [x] Implement search filtering (\`search.py\`).
- [ ] Verify empty queries and no-result behavior.
- [ ] Record verification and the next action.

Status: In progress. Filtering exists; edge-case verification remains.'''
new = f'''## 2026-09-02 - Add search filtering (owner: agent-a)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Implement search filtering (\`search.py\`).
- [x] Verify empty queries and no-result behavior. (done in {a_sha}, not redone)
- [x] Record verification and the next action.

Status: Complete. Edge-case behavior verified in test_search.py; implementation landed in {a_sha} while the ledger still showed the step open.'''
if old not in text:
    raise SystemExit('expected original entry block missing')
audit = f'''## {today} - Audit the handoff ledger against current state (owner: agent-b)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Audit each apparently unfinished entry against later commits and current source.
- [x] Run the test suite to confirm the claimed edge-case behavior (\`test_search.py\`).
- [x] Update the ledger to the effective status and validate it.

Status: Complete. agent-a already implemented empty-query handling in {a_sha}; agent-b verified with tests and closed the stale open box without redoing that commit.

'''
Path('ledger-next.md').write_text(text.replace(old, new, 1).replace('# Handoff\n\n', f'# Handoff\n\n{audit}', 1))
"

python3 "$GUARD" apply --root . --expect-version "$VERSION" --content ledger-next.md >/dev/null
python3 "$GUARD" validate --root . >/dev/null
sleep 1.2

echo
echo '# one ledger, two agents, no work redone'
sleep 1.2
git --no-pager diff HEAD -- HANDOFF.md
sleep 4.0
