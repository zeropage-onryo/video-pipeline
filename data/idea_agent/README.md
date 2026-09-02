# The idea agent's drop box

Claude leaves research here as plain JSON; `run_morning_prompts.sh` banks
it at 6am with `python -m ops.bank ingest data/idea_agent` and moves each
plan into `done/`. Nothing here is read at any other time, and an empty
folder is a normal night — the crawl and `prompts/sparks.txt` carry it.

One file per run, named for the day. Shape:

```json
{
  "agent": "claude/idea-agent",
  "created_at": "2026-09-01T05:10:00Z",
  "sparks": [
    {
      "brand": "zeropage",
      "spark": "the situation, six words or so — something a person DOES",
      "turn": "what goes wrong, changes, or repeats",
      "stake": "the feeling this is about, and who recognises it",
      "rationale": "the human beat found under the signal",
      "evidence": "what was actually observed — counts, dates, a handle",
      "images": [
        {"url": "https://...", "source_url": "https://...", "title": "..."}
      ]
    }
  ]
}
```

`brand` is `antihero` or `zeropage`. **`stake` is required** — an entry
without one is refused and named in the log, which is the rule
`prompts/scout_digest_prompt.txt` already states enforced in code. A spark
with no feeling under it is a weird GIF, and four camera specs banked at
0.80 with no stake between them is why. `source_url` is required on every
image — these are other people's frames and the composer shows the
attribution on each tile. Images are fetched at ingest time, so a link
that has expired by 6am banks nothing; the spark still runs.

To see what would happen without touching anything:

    venv/bin/python -m ops.bank ingest data/idea_agent --dry-run
    venv/bin/python -m ops.bank list --unused
