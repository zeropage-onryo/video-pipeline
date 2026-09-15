"""Age masters into Infrequent Access; leave thumbnails in Standard.

Storage in this studio is a RATCHET. "Leaving the board is archiving,
never deleting" is the right rule for a filmmaker's bin -- an idea
killed in March is evidence, and a renderer's output is expensive to
make twice -- but it means per-account bytes only ever grow, where every
other platform's plateau. Tiering is how that promise gets kept without
the cost curve following it.

The split is the whole reason the key scheme has two top-level prefixes
(src/media.py):

  m/  masters      full-size photos and rendered clips. Read at render
                   time and almost never again. -> Infrequent Access
                   after HOT_DAYS: two thirds the storage price, with a
                   per-GB charge on the way back out.
  t/  derivatives  the 480px tiles every card draws, every time. These
                   are exactly what must NOT move: a retrieval fee on
                   the thing read most often is the tiering decision
                   made backwards.

Nothing here expires or deletes anything, and no rule ever will --
Infrequent Access has a 30-day minimum billing period, so HOT_DAYS below
is deliberately not shorter than that: promoting an object and paying
its minimum twice costs more than leaving it alone.

    python -m ops.media_lifecycle            # show what is set now
    python -m ops.media_lifecycle --write
"""
from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from src import media, storage

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Not shorter than Infrequent Access's own 30-day minimum billing
# period -- see the module docstring.
HOT_DAYS = 30

# The flat keys everything lived under before the tenant scheme. They
# are never deleted (ops/migrate_media_keys.py COPIES), so once the
# studio is reading `m/` these are pure archive and belong in the cold
# tier with everything else.
LEGACY_PREFIXES = ("characters/", "props/", "locations/", "refs/",
                   "renders/", "clips/", "images/", "references/",
                   "soul-training/")


def rules() -> list:
    """The lifecycle configuration this repo intends. One rule per
    prefix, each named after what it does, so a rule found in the
    dashboard that is not in this list was added by hand and somebody
    should say why."""
    out = [{
        "ID": "masters-to-infrequent-access",
        "Status": "Enabled",
        "Filter": {"Prefix": f"{media.MASTER_PREFIX}/"},
        "Transitions": [{"Days": HOT_DAYS,
                         "StorageClass": "STANDARD_IA"}],
    }]
    for prefix in LEGACY_PREFIXES:
        out.append({
            "ID": f"legacy-{prefix.strip('/')}-to-infrequent-access",
            "Status": "Enabled",
            "Filter": {"Prefix": prefix},
            "Transitions": [{"Days": HOT_DAYS,
                             "StorageClass": "STANDARD_IA"}],
        })
    out.append({
        "ID": "abort-incomplete-uploads",
        "Status": "Enabled",
        "Filter": {"Prefix": ""},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
    })
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Set the media bucket's lifecycle rules.")
    parser.add_argument("--write", action="store_true",
                        help="apply them (default is to show both)")
    args = parser.parse_args(argv)

    if not storage.configured():
        print("R2 is not configured (the five R2_* vars) -- nothing to do.")
        return

    current = storage.get_lifecycle()
    have = [r.get("ID") for r in (current or {}).get("Rules", [])]
    print(f"currently set: {have or 'no lifecycle rules'}")
    print(f"this repo intends: {[r['ID'] for r in rules()]}")
    print(f"  thumbnails under {media.THUMB_PREFIX}/ are deliberately left in "
          f"Standard -- they are what every card reads.")

    if not args.write:
        print("\nreport only -- re-run with --write to apply.")
        return
    try:
        storage.put_lifecycle(rules())
    except Exception as e:                              # noqa: BLE001
        if "AccessDenied" not in f"{type(e).__name__}{e}":
            raise
        print(
            "\nRefused: AccessDenied.\n"
            "Lifecycle is a BUCKET-level operation and the R2 token in .env is\n"
            "scoped to Object Read & Write (ops/r2-setup.md step 2 says to scope\n"
            "it that way, which is right for everything else this repo does).\n"
            "Either:\n"
            "  - Cloudflare dashboard -> R2 -> the bucket -> Settings -> Object\n"
            "    lifecycle rules, and add the rules listed above by hand, or\n"
            "  - mint a second token with Admin Read & Write, export its\n"
            "    credentials for one run, and re-run this.\n"
            "Nothing was changed.")
        return
    print("applied. Nothing expires and nothing is deleted; objects older "
          f"than {HOT_DAYS} days move to Infrequent Access.")


if __name__ == "__main__":
    main()
