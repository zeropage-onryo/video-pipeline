## 2026-10-07 — getting the MCP server and a plugin ready for the Claude directory

Branch `claude/directory-listing-tasks-5fa35e`, six phases of
`docs/tasks/task-directory-listing.md`, one commit per phase, nothing pushed.
The plugin is a new local repo at `../zeropage-studio-plugin` (sibling of the
main checkout), one commit, not pushed. The write-ups are
`docs/directory/{REQUIREMENTS,AUDIT,OAUTH_TEST,RENDER_DESIGN,SUBMISSION}.md`.

**What was found.** The connector checklist refuses connectors that
"generate images, video, or audio through AI models" — which is what
`imagine_reference` does on the always-on list and what any render tool
would do. No tool carried a `title`, and the descriptions were written for
the operator's agent ("the nightly", "the Dev Studio", a venv command).
There is **no consent page**: Supabase's OAuth 2.1 server redirects the
person to `<Site URL><Authorization Path>?authorization_id=…`, a page we
must serve, and nothing in `app/` or `web/` does — so the connector cannot
be connected from claude.ai at all yet. A first-time OAuth caller gets a 403
(the mount never calls `provision_personal`). The sparks bank and the
reference bin are shared tables by design, so `sparks` / `images` list every
account's rows to every caller. There was no rate limit, and token
verification checked signature and audience but not the issuer. `capture` /
`pick` / `shoot` / `archive` ignored the explicit account the Guide builds
its server for. The image tools this session's stdio server shows
(`generate_image`, `image_models`) are uncommitted in the main checkout and
not on `main`, so not deployed.

**What landed on the branch.** A fixed-window rate limit on the mount keyed
on the resolved account (120/min; the operator key 1200/min; 429 +
`Retry-After`; in-process, one Fly machine, said in a comment). An issuer
check in `mcp_auth.verify`. Tests: the token cases, the rate limit, and
cross-tenant isolation through the REAL streamable-HTTP app for every tool
that takes an id; the sparks/images case is `xfail(strict)`. Phase 4: every
tool published from constants with a title and all four hints, descriptions
a stranger can act on with a vocabulary screen, enums for status / brand /
lanes, brand defaulted, listing caps named with a `truncated` note, `images`
erroring on an unknown id, the explicit-account fix. Suite: 3087 passed / 8
xfailed before, 3116 passed / 9 xfailed after (29 new tests plus one strict xfail); ruff clean.

**Decisions (Mike, same day).** Render path **B**: the connector generates,
every spend quoted and approved in chat — recorded in RENDER_DESIGN.md with
the build order (quote / approve tools on `pricing.sign` + `src/charge.py`,
the `queue_approve` body lifted into a callable, `imagine_reference` gaining
the same shape, a Create cap before the engine flag is set on Fly). Not
built. The AI-media rule stays the open review risk and the pack says so.
First contact: require one web sign-in (the 403 text still to change).
License MIT; support = GitHub issues on the plugin repo.

**Waiting on whom.** Mike: the three open items (sparks fence, `reference`'s
URL arguments, the Create cap); the consent-page build and the quote/approve
build; push + PR; the second-account live script (`OAUTH_TEST.md`) with
`zp-billing-test`; `fly releases` for the live commit; the GitHub repo for
the plugin; the icon; the portal. Anthropic: nothing yet.
