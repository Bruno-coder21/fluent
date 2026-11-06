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
> Done: adoption with a live progress message, the guard (checks every terminal command
> before it runs), risk prompts through Hermes's own approval, learning offers, counters.
> Tested on 311 real valid commands (0 blocked) and 17 typical AI mistakes (17 caught).
> Next: dashboard rings, `@cli:` references, Portuguese, catalog submission.

## What it looks like

```
agent> ffmpeg -y -i in.mp4 -c:v libx264 --crf 28 out.mp4
🛡️ fluent caught `--crf` in ffmpeg → `-crf`
agent> ffmpeg -y -i in.mp4 -c:v libx264 -crf 28 out.mp4      ✓
```

The guard only speaks when it is sure: it judges long options only, on commands it read
with high confidence, for the exact binary it read (path, size and date must match), on
the local terminal backend. Short options, positional arguments, unknown subcommands
(aliases, plugins, extensions) and anything known only at run time (`$VAR`, globs) are
never judged.

## Try it

```
/fluent adopt git          # learn git from its own help and man pages
/fluent show gh repo delete
/fluent forget git         # every action can be undone: /fluent undo
```

What adopting does: fluent runs `<program> --help` (and `<program> <command> --help`
for programs whose help style is known to handle it safely), reads the program's man
pages, and saves a card under `<HERMES_HOME>/plugin-data/fluent/`. It never runs a real
command: no shell, stdin closed, an empty working directory, pagers disabled, 5 s per
call, 25 s per program.

## Develop

```bash
scripts/test.sh                 # unit tests (throwaway uv env, Python 3.14)
scripts/capture_fixtures.sh     # refresh help/man fixtures from this machine
hermes plugins validate . --install-deps
```

## License

MIT
