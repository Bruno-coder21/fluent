# fluent

**Your agent becomes fluent in any program.**

Hermes already checks the code it writes. `fluent` checks the shell commands it runs.

It reads the `--help` and `man` pages of the command-line programs installed on your
machine (the version you actually have), and checks every terminal command the agent
runs against them, before it runs:

- an invented flag is caught with the right fix, so the agent corrects itself instead of
  failing and retrying;
- a destructive subcommand (for example `gh repo delete`) goes to Hermes's own approval
  prompt, explained in plain words;
- when the terminal says "unknown option", fluent offers to learn that program.

When everything is fine, fluent stays silent.

> Status: work in progress for the Hermes Agent Plugin Hackathon (November 2026).
> Day 1: command-line splitter and plugin skeleton. Adoption, guard and dashboard are next.

## Develop

```bash
scripts/test.sh                 # unit tests (throwaway uv env, Python 3.14)
scripts/capture_fixtures.sh     # refresh help/man fixtures from this machine
hermes plugins validate . --install-deps
```

## License

MIT
