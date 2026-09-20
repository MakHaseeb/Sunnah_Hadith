"""
Read configuration from a project-local .env file.

WHY THIS EXISTS
---------------
Claude Code snapshots the shell environment when a session starts, so a
key exported in an interactive terminal afterwards never reaches the
tooling -- and neither does one added to ~/.zshrc mid-session. Reading a
file at RUNTIME sidesteps all of that: the value is picked up whenever a
script actually runs, by whoever runs it.

Real environment variables always win, so CI or a properly exported shell
is unaffected by the presence of a .env file.

The .env file holds a live credential. It is listed in .gitignore and
must never be committed.
"""
import os

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env(path=ENV_PATH):
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    if not os.path.exists(path):
        return {}
    loaded = {}
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            loaded[key] = value
            os.environ.setdefault(key, value)   # real env wins
    return loaded


def has_anthropic_credentials():
    load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
