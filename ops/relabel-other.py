"""One-off: relabel the archive reason "other" as "weak concept".

"other" was never an edge case. It was 10 of the first 13 rejections,
and it meant "I just didn't like the idea" -- the commonest and most
important verdict the board produces. Named "other" it reads as
unsorted noise and teaches nothing; named honestly it is the clearest
statement this system has about generation quality.

    venv/bin/python ops/relabel-other.py
"""
import sys
from pathlib import Path as _P

# Run as `venv/bin/python ops/<name>.py` from anywhere: the repo root
# is not on sys.path unless the project happens to be pip-installed.
sys.path.insert(0, str(_P(__file__).resolve().parent.parent))

from src import accounts, db, preprod


def main():
    account_id = accounts.resolve_account(path=db.DB_PATH)
    # Scoped by account_id, like every other write against an owned
    # table -- tests/test_tenancy.py scans ops/ for exactly this and it
    # caught the unscoped version of this line.
    with db.connect(db.DB_PATH) as conn:
        n = conn.execute(
            "UPDATE shoot_concepts SET archive_reason = 'weak concept' "
            "WHERE archive_reason = 'other' AND account_id IS ?",
            (account_id,),
        ).rowcount
    print(f"relabelled {n} row(s)")
    print("tally now:", preprod.reason_counts(path=db.DB_PATH, account_id=account_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
