# Notes for anyone (or any assistant) working on this repo

Read `docs/PROJECT_HANDBOOK.md` first — it explains the whole project, every decision and how to
change things safely.

## Non-negotiable rules
- Every commit's author and committer is `n3h4a <nehakaramchandani2005@gmail.com>`, unsigned.
- Never add Co-Authored-By, session links, "Generated with …" or any other attribution to
  commits, pull requests, code, docs or comments.
- Never modify `dashboard/spotify_dashboard.pbix` (the owner's original design).
- Never hand-edit generated outputs; change the generator and run `make all`.
- No pull requests unless the owner asks.

## Before every commit
```bash
make all && make lint && make test   # and `make e2e` if site/ or its data changed
```
Commit the regenerated reports and JSON too — CI fails if they are stale.
