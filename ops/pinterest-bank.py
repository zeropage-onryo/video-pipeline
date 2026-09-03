"""Bank a spark and the Pinterest stills that match it.

The crawl happens in a logged-in browser (Pinterest gates its search
behind one); this script is the half that can be scripted: fetch each
picked pin's original, normalise it through refbin so it lands as an
ordinary /refs/<sha>.jpg, record the spark as a scout finding, and hang
the images off that finding's own pass. Nothing new downstream --
bin_for_finding already knows how to read it.

The DB is copied to scratch and copied back because SQLite cannot take
its locks on the mounted filesystem this runs over (every open raises
'disk I/O error'). The copy-back is guarded on mtime: if anything wrote
to the real DB while we worked, we refuse rather than clobber it.
"""
import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402  (after the sys.path line above)

from src import refbin, scout  # noqa: E402

LIVE = ROOT / "data" / "pipeline.db"
SCRATCH = pathlib.Path(os.environ.get("ZP_SCRATCH", "/tmp")) / "pinbank.db"

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pinterest.com/"}


def fetch_pin(tail: str):
    """i.pinimg originals -> /refs/<sha>.jpg, or None."""
    url = f"https://i.pinimg.com/originals/{tail}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=refbin.FETCH_TIMEOUT)
        if r.status_code != 200 or len(r.content) > refbin.MAX_FETCH_BYTES:
            return None
        jpeg = refbin.to_jpeg(r.content)
        return refbin.save(jpeg) if jpeg else None
    except Exception:
        return None


def main(payload_path):
    payload = json.loads(pathlib.Path(payload_path).read_text())
    before = LIVE.stat().st_mtime_ns
    shutil.copy2(LIVE, SCRATCH)

    report = []
    for item in payload:
        cand = {k: item[k] for k in ("spark", "turn", "stake", "score")}
        cand["evidence"] = item.get("evidence", "")
        cand["sources"] = item.get("sources", [])
        fid = scout.record(item["brand"], cand, lanes="pinterest",
                           dsn=str(SCRATCH))
        pass_id = scout.agent_pass_id(fid)
        scout.set_pass_id(fid, pass_id, dsn=str(SCRATCH))

        banked = 0
        for tail, pin_id in item["images"]:
            url = fetch_pin(tail)
            if not url:
                continue
            row = scout.bin_add(
                item["brand"], pass_id, url,
                source_url=f"https://www.pinterest.com/pin/{pin_id}/",
                title=item["spark"][:60], lane="pinterest",
                dsn=str(SCRATCH))
            if row:
                banked += 1
        report.append({"finding": fid, "pass": pass_id,
                       "banked": banked, "spark": item["spark"][:60]})

    if LIVE.stat().st_mtime_ns != before:
        print("REFUSED: pipeline.db changed while we worked; nothing written.")
        print(json.dumps(report, indent=2))
        return 1
    shutil.copy2(SCRATCH, LIVE)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
