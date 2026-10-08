# Directory requirements — the rubric

Read off the published pages on 2026-10-07 (Phase 0 of
`docs/tasks/task-directory-listing.md`). Every later phase grades against the
item numbers here: `AUDIT.md` carries PASS / FAIL / UNKNOWN per item,
`SUBMISSION.md` carries the status table.

Wording in quotation marks is the page's own. Anything not quoted is a
paraphrase and is marked as such. All seven pages the task names were
reachable; the index at https://claude.com/docs/llms.txt placed two of them
under new titles (`review-criteria` is now "Connector pre-submission
checklist") and added pages this file also reads: `authentication`,
`testing`, `plugins/build`.

Sources:

- D = https://claude.com/docs/directory/publish
- RC = https://claude.com/docs/connectors/building/review-criteria
- CS = https://claude.com/docs/connectors/building/submission
- AU = https://claude.com/docs/connectors/building/authentication
- TE = https://claude.com/docs/connectors/building/testing
- PC = https://claude.com/docs/plugins/pre-submission-checklist
- PS = https://claude.com/docs/plugins/submit
- PQ = https://claude.com/docs/plugins/quickstart
- PB = https://claude.com/docs/plugins/build

---

## Both (the directory itself)

| # | Requirement | Source |
|---|---|---|
| B1 | **Who can submit.** "Plan: Pro, Max, Team, or Enterprise. Free accounts can't submit." On Pro/Max "you submit from your own account and there's no role to check." | D |
| B2 | **Two submissions for one product.** "For your own product, make two submissions: the server as an MCP connector, then the plugin bundle whose skills teach Claude how to use it. Point the bundle's MCP server configuration at the same URL, so people who have both see one set of tools rather than two." | D |
| B3 | **Always submit the server as a connector**, even when a plugin references it: "If you have a remote MCP server, always submit it as an MCP connector, even when a plugin you're submitting already references it." | D |
| B4 | **Terms.** "Every listing is subject to the Anthropic Software Directory Terms and Software Directory Policy." (support.claude.com articles 13145338 and 13145358) | D, CS, PS |
| B5 | **Where.** Submit and maintain at `https://claude.ai/directory/manage`; "Select Submit new", then "Plugin bundle" or "MCP connector". | D |
| B6 | **Review.** Connectors: "every submission is scanned automatically for policy compliance and, by default, listed as a Community connector." Plugins: "every version gets automated validation and a security scan, and a person reviews a new listing before it goes live." | D |
| B7 | **Pairing.** "when the connector and a plugin bundle that references it are submitted from the same organization, you can pair the two listings." | D |
| B8 | **Skills alone are not a submission.** "Skills aren't a submission type on their own. Put them in a bundle." | D, CS |

## Connector

### Tool design (RC "Design tools that pass review")

| # | Requirement | Source |
|---|---|---|
| C1 | **Separate read and write tools.** "A single tool that accepts both safe HTTP methods ... and unsafe methods ... is rejected." "Split a catch-all tool into a read-only tool and one or more write tools. Ideally, split write operations further by action type: create, update, and delete." | RC |
| C2 | **Custom query tools name the API.** Applies "only to custom query tools" that "accept freeform endpoint paths, query strings, or request bodies". Purpose-built tools "don't need an API docs reference." | RC |
| C3 | **Tool annotations.** "Every tool must include a `title` and the applicable hint: `readOnlyHint: true` for read-only tools, and `destructiveHint: true` for tools that modify or delete data. These determine auto-permissions in Claude. Read-only tools can run without per-call confirmation, and destructive tools always prompt." The portal "flags tools that are missing them". | RC, CS |
| C4 | **Tool names ≤ 64 characters.** "Tool names must be 64 characters or fewer." | RC |
| C5 | **Narrow, accurate descriptions.** "Each tool description should state precisely what the tool does and when to invoke it. The description must match the tool's actual behavior." | RC |
| C6 | **No prompt-injection patterns.** "Describe what the tool does, and don't tell Claude how to behave." Rejected if descriptions "Instruct Claude to call external software or tools the user didn't request", "Interfere with Claude calling other tools", "Direct Claude to pull behavioral instructions from external sources", "Contain hidden, obfuscated, or encoded instructions", or "Tell Claude to behave in ways unrelated to the tool's function, attempt to override system instructions, or promote products and services". | RC |

### Server behaviour and scope (RC)

| # | Requirement | Source |
|---|---|---|
| C7 | **Every tool succeeds on valid input; no generic errors.** "Every tool must return a successful response when called with valid parameters, and generic errors such as 'Internal Server Error' or 'Bad Request' with no detail fail review." | RC |
| C8 | **Validate inputs, actionable errors.** "Validate inputs and return actionable error messages rather than silently accepting invalid data." | RC |
| C9 | **Reasonably sized responses.** "Keep responses reasonably sized for the task, and don't return a full database dump when a summary was requested." | RC |
| C10 | **No conversation-data collection.** "Don't collect conversation data beyond what the tool needs for its function." "Don't query Claude's memory, chat history, conversation summaries, or user files." | RC |
| C11 | **API ownership.** "Your server must call your own first-party APIs, or APIs you legitimately proxy. The MCP server domain should match your service." | RC |
| C12 | **Unsupported use cases.** "Connectors that do the following aren't accepted: Transfer money, cryptocurrency, or other financial assets; **Generate images, video, or audio through AI models**." ("Design tools that produce diagrams, charts, or UI mockups are allowed.") The Compliance step has a matching acknowledgment ("AI media generation"). | RC, CS |

### Authentication (AU, CS)

| # | Requirement | Source |
|---|---|---|
| C13 | **OAuth 2.0 for authenticated services.** "Authentication: use OAuth 2.0 for authenticated services." Supported by default: `oauth_dcr` (Dynamic Client Registration, RFC 7591) and `oauth_cimd`. | CS, AU |
| C14 | **401 starts sign-in.** "A `401` is required to start sign-in, and Claude ignores a `WWW-Authenticate` header on a `200` response." The 401 must carry `WWW-Authenticate: Bearer resource_metadata="<url>"`. | AU |
| C15 | **Protected resource metadata.** "Make `resource` match your MCP server URL exactly: the document's `resource` field must equal the URL as the user enters it in Claude, including any path component." "List your primary issuer first ... If you list more than one, Claude uses the first entry and doesn't fall back." | AU |
| C16 | **Authorization server metadata reachable.** "your authorization server must serve its own discovery metadata, either RFC 8414 ... or OpenID Connect Discovery 1.0, at its `/.well-known/` paths" and be reachable from Anthropic's egress range `160.79.104.0/21`. | AU |
| C17 | **DCR or CIMD.** With no `registration_endpoint`, "Claude selects CIMD only when your authorization server metadata advertises both `client_id_metadata_document_supported: true` and `none` in `token_endpoint_auth_methods_supported`." For high traffic, "prefer CIMD or `oauth_anthropic_creds` over DCR. DCR causes Claude to register a new client on every fresh connection". | AU |
| C18 | **PKCE S256.** "Claude includes a PKCE `code_challenge` with `code_challenge_method=S256` on every authorization request ... Your authorization server must support S256 PKCE" and advertise `code_challenge_methods_supported: ["S256"]`. | AU |
| C19 | **Scopes.** "To control which scopes Claude requests, include a `scope` parameter in the `WWW-Authenticate` header on your `401` response. If you don't, Claude requests the scopes your protected resource metadata advertises in `scopes_supported`." | AU |
| C20 | **Callback URLs.** Hosted apps: "register exactly this redirect URI: `https://claude.ai/api/mcp/auth_callback`". Claude Code: "accept a loopback redirect on any port" for `http://localhost/callback` and `http://127.0.0.1/callback`, port ignored. | AU |
| C21 | **Consent screen shows the redirect host.** "On your consent screen, display the redirect URI's hostname clearly." | AU |
| C22 | **Token endpoint.** Accept `application/x-www-form-urlencoded`; on a dead refresh token return `invalid_grant`; rotate refresh tokens for public clients. | AU |
| C23 | **Endpoint latency.** "Claude waits up to 10 seconds for a response from your OAuth discovery, registration, and token endpoints, and up to 30 seconds for refresh token requests." | AU |
| C24 | **No tokens in the URL.** "don't read tokens from query parameters such as `?token=` or `?apiKey=`". | AU |

### What to submit with it (CS, RC, TE)

| # | Requirement | Source |
|---|---|---|
| C25 | **Remote and HTTPS.** "Your server is remote and reachable over HTTPS: the portal asks for an `https://` URL." | CS |
| C26 | **Tested in Claude.** "add the server as a custom connector and call each tool from a conversation; the portal's Test & launch step asks you to confirm this." Also "Exercise every tool through the MCP Inspector". | CS, RC, TE |
| C27 | **Listing materials.** "documentation URL, privacy policy URL, support contact, an icon". Listing fields: "server name up to 100 characters, one-liner up to 200 characters, description up to 2,000 characters, one to five categories, documentation URL, privacy policy URL, support contact, icon, and the URL slug for your listing page. The slug is permanent once published." | CS |
| C28 | **Test account.** "Test credentials: required, and they must be for a fully populated account." "Provide a fully populated account rather than an empty shell ... Include step-by-step setup instructions for someone unfamiliar with your service." Entered in the portal, "which only reviewers see". | RC, CS, TE |
| C29 | **Public documentation by publish date.** "Public documentation: required by your publish date. A blog post or help-center article is sufficient". | RC |
| C30 | **Use cases step.** "The primary use cases, what users need before they can connect, such as accounts, plans, or other setup, and whether the connector reads data, writes data, or both." | CS |
| C31 | **Company step.** "Company name and website, plus a primary contact for review updates." | CS |
| C32 | **Data handling step.** "Whether the underlying API is your own, proxied from a partner with permission, or a third party's you don't control, and whether the connector handles personal health data or sponsored content." | CS |
| C33 | **Compliance step.** "Seven policy acknowledgments covering the directory guidelines, first-party API usage, financial transactions, AI media generation, prompt injection, conversation data collection, and public documentation. All seven are required." | CS |
| C34 | **Obligations after submitting.** "Maintain your connector's security and functionality; Respond to security issues promptly; Provide accurate descriptions and documentation". | CS |
| C35 | **Detail card description is yours.** "You write the detail card description in the submission portal, and Anthropic can't edit it." | CS |
| C36 | **Allowed link URIs** (only if the server calls `ui/open-link`) — optional; "Every origin and scheme you list must be owned by you". Not applicable: this server opens no links. | CS |
| C37 | **Carousel screenshots** — "An MCP App submission includes screenshots"; PNG, ≥1000 px wide, 3–5. Not applicable: this server has no MCP App UI. Screenshots are still useful for the review-team note and for the plugin README. | CS |
| C38 | **Privacy policy for local connectors** (README section + `privacy_policies` in `manifest.json`) — applies to MCPB bundles, which the directory no longer accepts. Not applicable to a remote server; the portal still asks for the privacy policy URL (C27). | CS |
| C39 | **Don't gate behaviour on `clientInfo`.** "Don't gate behavior on an exact `name` or `version` string ... it must never feed an authorization decision." | TE |
| C40 | **Escalation contact:** `mcp-review@anthropic.com`. | CS |

## Plugin

### Folder and manifest (PQ, PB, PC)

| # | Requirement | Source |
|---|---|---|
| P1 | **Layout.** A plugin is a folder with `.claude-plugin/plugin.json` and components beside it: `skills/<name>/SKILL.md`, `.mcp.json`, `README.md`, `LICENSE`. "Put only the manifest inside `.claude-plugin/`. Everything else goes at the plugin's top level." | PQ, PB |
| P2 | **Manifest fields** read by every surface and the directory: `name`, `displayName`, `version`, `description`, `author: {name, url}`, `license`. "Set `description`, `author`, and `version`" (warning if not). | PQ, PB, PC |
| P3 | **Name rules.** "Use a `name` made of lowercase letters, digits, and hyphens, up to 64 characters, that starts and ends with a letter or digit". "never change it after release". Not "a reserved word such as `claude`, `anthropic`, `official`, `plugin`, `mcp`, or `test` as the whole name" and "nothing that presents the plugin as official". A name "made only of generic words" is held for a reviewer. Must not match another organization's plugin or a well-known brand. | PC, PQ |
| P4 | **Writing system.** "Write `displayName` and `author.name` in one writing system, without look-alike letters or invisible characters". | PC |
| P5 | **Version.** "If your `plugin.json` sets `version`, raise it with every release." | PS |
| P6 | **README ≥ 40 words.** "Put a README of at least 40 words in the plugin folder, preferably named `README.md`. Words inside code blocks don't count." "Say what the plugin does, how to use it, and what data it sends." "The directory shows your README as the listing's description". | PC, PQ |
| P7 | **License.** "Add a `LICENSE` file to the plugin folder, or set `license` in `plugin.json`" (Blocks otherwise). | PC |
| P8 | **System files.** "Remove `.DS_Store`, `Thumbs.db`, `desktop.ini`, and `__MACOSX` entries from the plugin folder" (Blocks). | PC, PQ |
| P9 | **Portable names.** "no colon, no trailing dot or space, no Windows device name such as `con.md` or `prn`, and no two names that differ only by capitalization"; path folders "letters, digits, dots, hyphens, and underscores only". | PC |
| P10 | **Size.** Repository under 50 MiB archived / 256 MiB unpacked, < 10,000 entries, every file < 5 MiB; files that aren't images/fonts < 256 KiB and ≤ 512 files (held otherwise). | PC |
| P11 | **Text files only.** "Include only text files, SVG included, complete PNG, JPEG, GIF, and WebP images, and font files." Any other binary is held. | PC |
| P12 | **No symlinks / submodules / LFS** for anything the plugin loads. | PC |

### MCP reference and secrets (PQ, PB, PC)

| # | Requirement | Source |
|---|---|---|
| P13 | **`.mcp.json` shape.** `{"mcpServers": {"<name>": {"type": "http", "url": "https://.../mcp"}}}`. "Give each remote MCP server a `type` of `http`, `sse`, or `ws` and a `url` that is an absolute `https://` or `wss://` URL". Must be valid JSON matching the MCP schema (Blocks). | PQ, PB, PC |
| P14 | **Same URL as the connector.** "If your server is already listed in the directory, use the same URL here, so that someone who has both your connector and your plugin sees one set of tools rather than two." | PB, D |
| P15 | **No secrets.** "Don't put API keys or other secrets in this file, because every person who installs the plugin receives its files." "Keep real credentials out of every file, documentation and examples included." Don't read `$GITHUB_TOKEN`-style env credentials. | PQ, PC |
| P16 | **No launchers / bundles.** Declare servers "with `command` and `args` or with `url`, not a `.mcpb` or `.dxt` bundle"; pin any `npx`/`uvx` package to an exact version. Not applicable: this plugin runs nothing locally. | PC |

### Skills (PQ, PB, PC)

| # | Requirement | Source |
|---|---|---|
| P17 | **Skill file.** "A skill is a `SKILL.md` file in its own folder under `skills/`, and the folder name matches the skill's `name` field." | PB |
| P18 | **Frontmatter.** "Write valid YAML front matter in each skill, command, and agent file, with `description` as a single text value, not a list" (Blocks if it does not parse). | PC |
| P19 | **Description = the situations.** "Claude decides when to load the skill from the `description` line, so write it as the situations a user would be in, not as a summary of the file." | PQ, PB |
| P20 | **Exact folder names.** "Name component folders and files with the exact spelling and capitalization Claude Code expects, such as `hooks/`, `skills/`, and `SKILL.md`". | PC |
| P21 | **Supporting files** go in `references/`, `assets/`, `scripts/` beside `SKILL.md`, each mentioned in `SKILL.md`. | PB |

### Validation, repository, submission (PC, PS, PQ)

| # | Requirement | Source |
|---|---|---|
| P22 | **Local validator.** "claude plugin validate ./your-plugin" from the parent folder; "A plugin with no problems prints `✔ Validation passed`." It "only checks that your files are well-formed" — the portal's Validate runs the directory checks (README, license, name). | PC, PQ |
| P23 | **Test it loaded.** "claude --plugin-dir ./<plugin>" shows the skill as `/<plugin>:<skill>` and `/mcp` shows the server; on claude.ai, "Customize > Plugins > Add > Upload plugin" with a zip. | PQ, PB |
| P24 | **GitHub repository, public before going live.** "The directory reads plugins from repositories on github.com." "The repository can stay private while you validate and submit, and must be public before the listing goes live." The connected GitHub account must be able to push to it. | PS, PQ |
| P25 | **One submission per repository folder; first organization owns it.** "the first organization to submit a given repository folder holds that listing". Up to 10 submissions per 24 hours. | D, PS |
| P26 | **Portal steps.** Source (repository, plugin path, branch or tag) → Validate → Listing details (from `plugin.json` + README) → Data handling ("whether the plugin reads or stores personal data, whether it sends data to services other than its declared connectors, how long it keeps data, and whether it's intended for people under 18") → Compliance (contact email + "all four acknowledgements") → Review and submit (webhook or scheduled check). | PS |
| P27 | **Security scan.** "Describe in the README everything the plugin runs, sends, or fetches." "Commit readable source instead of compiled, packed, or minified code." A first submission that fails the scan is rejected. | PC |
| P28 | **Updates.** "Merge to the tracked branch, and the directory picks up the commit, checks it, and publishes it." A publish is a request a reviewer acts on by default. | PS |
| P29 | **Surfaces.** Skills load in chat, Cowork and Claude Code; a remote server in `.mcp.json` "appears on the plugin's Connectors tab in chat and Cowork ... Claude Code connects to it directly". "A top-level `bin/` directory stops claude.ai and Cowork from installing the plugin at all." | PB |
| P30 | **Escalation contact:** `directory@anthropic.com`. | D, PS |
