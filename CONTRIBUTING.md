# Contributing

This repository is the public command line client for Reviso. Keep changes
focused and public-safe.

## Rules

- Read [VISIBILITY.md](VISIBILITY.md) before adding anything. It lists what must
  not appear here.
- Do not add server-side logic. If a change needs the server to do something new,
  that belongs in the server, and this client calls it.
- Do not add a runtime dependency without a strong reason. The client is
  stdlib-only on purpose so it can be installed into an agent's environment
  cheaply.
- Do not add secrets, keys, or real tokens, including expired or obviously fake
  ones: a token prefix is itself information.
- Do not weaken the base-version behaviour. Sending a write without the version
  the agent read is the failure this client exists to make visible.

## Tests

```bash
pip install -e ".[test]"
pytest
```

Tests run against a fake HTTP server. Do not add a test that needs a live Reviso
instance; live-stack verification is a separate, deliberate exercise.

## Reporting problems

Open an issue for the client: a command that misbehaves, an error that is hard to
act on, or a response shape that changed. For problems with the Reviso product or
an account, use the support channel on the product site.
