# reviso-cli

Command line client for [Reviso](https://reviso.work), a content collaboration
system where agents publish Markdown and HTML drafts and a human team reviews
them.

This is the client half of Reviso. It talks to a Reviso server over HTTP and
contains no server code. It has **no runtime dependencies**: the transport is
`urllib`, so publishing a Markdown file does not pull a dependency graph into an
agent's environment.

## Install

```bash
pip install reviso-cli
# or run it without installing
uvx --from reviso-cli reviso --help
```

Installs the `reviso` command. No runtime dependencies: installing it will not
pull a dependency graph into an agent's environment.

## Quick start

```bash
reviso auth login --server https://reviso.work
# opens a browser for consent; use --no-browser to open the URL yourself
reviso doctor --json

reviso publish draft.md --title "Q3 launch plan" --description "Initial draft"
# prints the document URL
reviso publish draft.md --title "Q3 launch plan" --json
# prints document_id, version_id, workspace_id, and review_url

reviso documents --json                 # find the document id
reviso packet doc_abc123 --format json  # reviewer comments and version metadata
reviso versions doc_abc123              # read the current version id

reviso update doc_abc123 revised.md \
  --description "Address reviewer feedback" \
  --base-version-id ver_xyz
```

## Browser login

Version 0.2 supports browser consent with a temporary loopback callback and PKCE.
Keep the CLI running and open the login URL in a browser on the same computer.
`reviso auth status` shows the selected server and login state without credentials;
`reviso auth logout` removes that server's saved login. Revoke the connection in
Settings → Integrations to end its server access.

Credentials live in an owner-only file at `~/.config/reviso/credentials.json`
(or under `XDG_CONFIG_HOME`), separately for each server, and refresh automatically.
An existing `REVISO_AUTOMATION_KEY` or `--key` still supports headless use.
The credential lock currently supports macOS and Linux.

## The rule that matters

**`update` and `rollback` require `--base-version-id`.**

The base is the version you actually read. Without it, a write could silently
discard a human's concurrent edit, so the CLI fails before contacting the server.
The safe shape is two steps:

```bash
reviso versions <document_id>        # take the newest version_id
reviso update <document_id> file --description "..." --base-version-id <ver_...>
reviso rollback <document_id> <target_version_id> \
  --description "..." --base-version-id <ver_...>
```

If a write is rejected as a conflict, re-read and re-apply your change on top of
the human's edit. `--force-latest` is the explicit last-writer-wins opt-in: it
performs one fresh read and uses that version as the base. It cannot be combined
with `--base-version-id`.

## Command groups

| Group | Commands |
| --- | --- |
| Connection | `auth`, `doctor`, `health`, `ready`, `version` |
| Documents | `publish`, `open`, `status`, `documents`, `search`, `packet` |
| Revisions | `versions`, `diff`, `update`, `rollback` |
| Reviewers | `invite`, `guest`, `comment`, `reply`, `resolve` |
| Data | `export`, `import`, `workspaces` |

## Deliberately not in this client

These are boundaries, not gaps to be filled later:

- **No server commands.** Starting a Reviso server is not part of the client.
- **No share-link creation.** A share link carries a bearer token in its URL, and
  creating one is a browser action where the person handing it out can see who it
  is going to. Invites by email are here instead.
- **No owner or operator surfaces.** Metrics, debug replay, and internal replay
  endpoints are not exposed.

If you need MCP tools rather than a shell, the hosted connector is the better
path in most hosts. See [reviso-agent](https://github.com/reviso-si/reviso-agent)
for the agent skill.

## Provenance

Publishing from an agent runtime binds provenance automatically when the runtime
exposes `DSH_SESSION_ID`. You can pass an explicit pair instead:

```bash
reviso publish draft.md --source-kind dsh --source-session-id <session_id>
```

`--source-kind` and `--source-session-id` must be supplied together. Use
`--no-source-binding` for an intentional no-source publish; it cannot be combined
with either provenance flag.

## License

MIT. See [LICENSE](LICENSE).

The Reviso product itself is **not** open source. This repository covers the
client only; it grants no rights to the service or its server software. See
[VISIBILITY.md](VISIBILITY.md) for the boundary this repository holds, and
[CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Publish a presentation with its explicit kind so the server validates and renders it as slides:

```bash
reviso publish presentation.html --workspace-id <workspace-id> --kind html_deck --deck-contract-version html-deck/1
```

Ordinary HTML keeps `--kind document` (the default); deck markup without `html_deck` is rejected by the server.
