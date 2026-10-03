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
uvx reviso-cli --help
```

Installs the `reviso` command.

## Quick start

```bash
reviso auth login --server https://reviso.work
# set REVISO_AUTOMATION_KEY in the environment first, or pass --key
reviso doctor --json

reviso publish draft.md --title "Q3 launch plan" --description "Initial draft"
# prints the document URL

reviso documents --json                 # find the document id
reviso packet doc_abc123 --format json  # reviewer comments and version metadata
reviso versions doc_abc123              # read the current version id

reviso update doc_abc123 revised.md \
  --description "Address reviewer feedback" \
  --base-version-id ver_xyz
```

## The rule that matters

**Always pass `--base-version-id` when you revise a document.**

Omitting it is not a safe default. Without it the command re-bases onto whatever
version is newest and lets your write win, which silently discards a human's
concurrent edit. The safe shape is always two steps:

```bash
reviso versions <document_id>        # take the newest version_id
reviso update <document_id> file --description "..." --base-version-id <ver_...>
```

If the write is rejected as a conflict, re-read and re-apply your change on top of
the human's edit. Do not retry with the flag removed.

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

## Known limitations

- `publish` prints only the document URL. It does not return the document id, so
  use `reviso documents --json` to continue from the id.
- `update` and `rollback` accept an omitted base version and fall back to
  last-writer-wins. Always pass the flag. A future release should make the safe
  behaviour the default.

## License

MIT. See [LICENSE](LICENSE).

The Reviso product itself is **not** open source. This repository covers the
client only; it grants no rights to the service or its server software. See
[VISIBILITY.md](VISIBILITY.md) for the boundary this repository holds, and
[CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
