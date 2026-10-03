# Visibility Policy

This repository is public. Reviso is a hosted product and is **not** open source.
This client is public because an agent integration nobody can read is an agent
integration nobody should trust. Everything else stays private.

Default stance: publish only what a reader needs to call the server correctly.

## Public

This repository may contain:

- The HTTP client: transport, request construction, and error handling.
- The command line surface a user types.
- The user-facing access vocabulary for invites (`view`, `comment`, `edit`) and
  what each one is called in the interface.
- Public response shapes the client parses, such as a document's version id.
- Scripts and tests that exercise the client against a fake server.

## Private

Keep the following out of this repository:

- Server source code, storage, migrations, and deployment configuration.
- The authorization model: how an access level expands into capabilities, the
  capability names themselves, and how an access decision is made.
- Operator and debugging surfaces: internal metrics, debug replay endpoints, and
  internal replay packets.
- Internal HTTP routes that are not part of the supported client surface.
- Credential validation rules, key prefixes, and break-glass mechanisms. The
  client carries a key and sends it; it does not describe what the server accepts.
- Local development plumbing such as port allocation, checkout-scoped state, and
  internal checkout layout.

## Why the client is public and the server is not

The client is a thin transport. Its value is that a reader can confirm exactly
what is sent, with which credential, and when -- which is what makes an agent
integration auditable. None of that requires publishing the authorization model,
and this repository is arranged so the two do not come out together: the client
sends an access *level* and lets the server decide what it means.

## Review Standard

Before publishing, ask whether the content helps someone call the server
correctly without helping them reconstruct anything in the private list.

The usual leak here is not source code. It is a comment explaining *why* the
server rejected a request, a docstring naming an internal function, or an example
that uses an operator endpoint to demonstrate an error path. Describe the
symptom the client sees; leave the reason on the server.
