"""
CI safety net — keep the track record complete and current WITHOUT the AU machine.

Runs from GitHub Actions (AFL API + CSV only; no Sportsbet, which needs an AU IP).
For every CONCLUDED round with no snapshot, it backfills the floors (deterministic,
leak-free) so the round can be graded; then it grades all pending rounds and
regenerates the public pages. This is what stops rounds silently dropping out of the
record when the local app is closed (what happened to R18/19/21/22).

It NEVER overwrites an existing snapshot — a round the AU machine already captured
WITH odds keeps its value picks; only genuinely-missing rounds get floors-only.
Idempotent: safe to run on a schedule; does nothing when everything's already graded.

    python ci_grade.py            # backfill missing -> grade pending -> rebuild pages
"""
import glob
import os
import re

import lineups as L
import scorecard as S
import backfill_snapshot as B
import results

YEAR = int(os.environ.get("PM_YEAR", "2026"))


def first_tracked_round(year):
    """Earliest round we have a snapshot for — tracking began here (R13 in 2026).
    We never backfill earlier rounds: they predate the tool and have no baseline."""
    rounds = [int(m.group(1)) for f in glob.glob(S.SNAP.format(year=year, rnd="*"))
              for m in [re.search(r"_R(\d+)\.json$", f)] if m]
    return min(rounds) if rounds else None


def concluded_rounds(year):
    """Rounds whose every game is CONCLUDED, per the AFL API (source of truth)."""
    token = L.get_token(verify=True)
    cid = L.compseason_id(year, token, True)
    out = []
    for rnd in range(1, 30):
        ms = L._matches(cid, rnd, token, True)
        if not ms:
            continue
        if all(m.get("status") == "CONCLUDED" for m in ms):
            out.append(rnd)
    return out


def main():
    done = concluded_rounds(YEAR)
    start = first_tracked_round(YEAR)
    print(f"concluded rounds {YEAR}: {done}   (tracking from R{start})")
    if start is None:
        print("no snapshots exist yet — nothing to track; exiting"); return

    backfilled = []
    for rnd in done:
        if rnd < start:
            continue                       # predates the tool; never backfill
        snap = S.SNAP.format(year=YEAR, rnd=rnd)
        if not os.path.exists(snap):
            print(f"R{rnd}: no snapshot -> backfilling floors (app was offline)")
            B.run(rnd, YEAR)
            backfilled.append(rnd)
    if backfilled:
        print(f"backfilled: {backfilled}")
    else:
        print("no missing snapshots to backfill")

    # grade every snapshotted-but-unfinalised round, then rebuild both public pages
    S.grade_pending(YEAR)
    S.report_md()
    results.main()
    print("safety net complete")


if __name__ == "__main__":
    main()
