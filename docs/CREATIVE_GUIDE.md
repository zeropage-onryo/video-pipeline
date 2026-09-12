# Creative guide on Create

Open Studio (`/ui`) and describe your idea in the main Create text box. Send (or Enter; Shift+Enter adds a line) starts the reasoning conversation. Follow-up replies use that same box, with suggested choices and the conversation directly above. The creative partner selector chooses Gemini or a separately connected personal model. Attach photos using the composer controls.

The editable brief appears within the composer when ready. Review it and choose **Create scenes** to generate 1–4 alternatives. Unsent replies disable generation until sent or cleared. Scene generation uses the scene model picker alongside that button. The guide never starts image/video renders by itself.

By default the conversation uses the existing `reasoning` brain (Gemini Pro with HIGH thinking and no cheaper-model substitution). You can instead choose your own ChatGPT or Claude connection in the guide. The model picker above still selects the model that writes the final concepts. Calls are recorded under `creative_guide` in the account's model usage. Missing keys, failed model calls and invalid replies are surfaced in the panel.

Completed replies now save automatically as private creative projects in Postgres. Use **Saved projects** to reopen a conversation, editable brief and reference selections after a reload or on another device. **Save project** saves manual draft edits and unsent text. New conversation preserves the previous saved project and starts a fresh composer. Unsaved work triggers the browser's leave-page warning. New uploads must be sent once before saving, so the server can persist their reference URLs.

Projects belong to both the signed-in user and active account. Every query checks both, and optimistic revisions refuse stale-tab overwrites. The new table enables RLS with no direct browser-access policy; the trusted server performs the scoped queries. The latest 100 projects appear in the picker. Conversations retain the existing 40-message limit. In-flight model jobs still use the in-process registry: a server restart can interrupt an unfinished turn; completed saved conversations survive. Personal-model sign-ins and credentials are never stored in a project snapshot.


Implementation: `src/creative_guide.py`, `prompts/creative_guide.txt`, `POST /api/creative-guide`, and `app/static/zpf/creative-guide.js`. The endpoint resolves brand and account from membership, reuses composer photo handling and scene grounding, then starts an account-owned background job. Test coverage in `tests/test_creative_guide.py` checks reasoning selection, history, image input, malformed replies, unavailable configuration, input validation and job isolation.


## Separate personal model sign-in

The guide's **Creative partner** menu offers Gemini, My ChatGPT, and My Claude. Choose **Connect model account** to manage sign-in independently of your studio account. Each connection belongs to the signed-in user AND active studio account. Switching brands does not borrow another connection. Personal models develop the brief; the existing Create model picker still controls final scene generation.

- **ChatGPT:** **Sign in with ChatGPT** starts the official Codex app-server device flow. Open the supplied OpenAI page, enter the displayed code and finish sign-in there. The guide lists models returned by that connection. Usage draws from your ChatGPT plan's Codex allowance, subject to provider limits and any credits you elect to buy. This connects Codex model access; it does not import ChatGPT chat history or memory.
- **Claude:** **Sign in through Claude Code** runs the installed, unmodified `claude auth login` command with a private configuration directory. It opens Claude's sign-in page on the studio computer. The browser must be on that computer at localhost, because the CLI owns a localhost callback. A remote hosted browser cannot complete this first version's Claude login; the UI explains that and disables the button. A separate desktop bridge is still needed for that workflow. Once connected, choose Sonnet, Opus or Haiku; the runtime resolves those official aliases. Usage is governed by the user's Claude plan.
- **Disconnect** signs that private runtime out. Personal-model errors never fall back to Gemini or an API key. The studio does not collect provider passwords, authorization codes, or session tokens through its HTTP API.

The runtime stores credentials in `data/model_sessions/<hashed-user-and-account>/<provider>/`. These directories are private (0700), excluded from Git and Docker image contents, and are not served as static files. The installed provider runtime handles credential persistence and refresh. The child environment excludes the server operator's API keys and login overrides. ChatGPT uses an isolated Codex configuration with file credential storage; Claude uses an isolated `CLAUDE_CONFIG_DIR`. Neither copies the operator's existing login.

## Runtime and verification

The production image bundles official Codex CLI 0.153.2 for ChatGPT sign-in. Install official Claude Code on the studio Mac for local Claude sign-in; hosted Claude sign-in still requires a desktop bridge. Fly's `/app/data` volume is where persisted model sessions would live. Use a single application worker for these in-process login sessions, like the existing job registry. Four active Codex connections are allowed; inactive runtimes are reaped on subsequent connection requests after 20 minutes. This is a small-studio implementation, not a distributed session service.

Both personal generators receive conversation context and supplied images with the same validated reply schema. Tool execution, MCP, plugins and workspace actions are disabled for the creative guide. No API-dollar estimate is manufactured for subscription calls; the completed job identifies `billing: personal_plan`, and the provider remains the authority for plan usage.

Tests cover scoped logins, credential environment isolation, disconnected and failed connections, cross-site mutation protection, tool restrictions, image transport, reply validation and personal generation without a Gemini key. Local smoke checks verified that fresh Codex and Claude configuration directories report signed out even while the operator has a personal login. The browser flow was exercised with simulated authentication and model responses. Real provider sign-in and an authenticated inference call remain a user acceptance step; no model allowance was spent in those checks.

Official integration references: [Codex app-server](https://learn.chatgpt.com/docs/app-server), [Claude Code CLI](https://code.claude.com/docs/en/cli-reference), [Claude Code integration conditions](https://code.claude.com/docs/en/legal-and-compliance), and [Claude subscription SDK usage](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan).
