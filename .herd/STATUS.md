# Herd Status

**Updated**: 2026-02-15
**Updated by**: Steve

## Active Work

_None. Clean slate post-v0.2.0._

## Blocked

_None._

## Awaiting Review

_None._

## Recently Completed

| Ticket | Agent | PR | Description |
|--------|-------|----|-------------|
| DBC-163 | Scribe | #13 | Docs rewrite for v0.2.0 |
| — | Mason | #12 | .env pattern, content path resolution, v0.2.0 bump |
| — | Rook | #11 | Sync herd content |
| DBC-159 | Rook | #9 | CI Vigil QA step, fixture renames per HDR-0024 |
| — | Rook | #8 | Roster rename per HDR-0024 |

## Stale Branches

12 merged feature branches remain locally. Cleanup candidate for next Rook chore.

## Notes

- HDR inventory: 33 decisions (HDR-0001 through HDR-0033)
- Current version: 0.2.0
- All adapter repos cloned locally and up to date
- Runtime deployed at ~/herd/ with DuckDB + LanceDB operational
- MCP server: 5 adapters loaded, 15 tools registered, zero raw SQL
- Env architecture locked (HDR-0030, HDR-0032)
- StoreAdapter refactoring complete (HDR-0031)
- LanceDB semantic memory live (HDR-0033) — herd_recall + herd_remember
- Remaining: dead code cleanup (db.py, schema.sql), test suite updates, seed LanceDB
