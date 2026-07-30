"""smash-mods: a Typer/Rich CLI wrapping the scripts/ tooling in this repo.

This package is a thin presentation layer. It never reimplements what a
script under scripts/ already does -- every subcommand just builds the same
argv a human would type by hand and runs it as a subprocess, so
`./scripts/deploy.sh --profile roster` and `smash-mods deploy --profile
roster` do exactly the same thing. The one exception is `smash-mods
profiles`, which reads profiles.toml directly (via scripts/common.py's
read-only helpers) since that command has nothing to shell out to.
"""

__version__ = "0.1.0"
