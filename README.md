# OpenClaw Foundation

A reusable company-neutral foundation for OpenClaw on macOS and Linux. It includes COS and operating agents, department blueprints, context and Bible instructions, bounded workflows, and preview/apply/rollback updates.

See [the setup guide](foundation/README.md) and [releases](https://github.com/klole/openclaw-foundation/releases). Early releases are candidates awaiting independent review. Each company supplies its own context and provider connections.

Python 3.9+; standard library only.

```sh
python3 -m unittest discover -s foundation/tests -v
```
