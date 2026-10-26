"""saba-chan XNA Framework 4.0 Extension Package.

Puts a pinned, portable copy of the XNA Framework 4.0 Refresh files next to a game server.
Re-exports the public API from the core module.
"""
from extensions.xna.xna import FILES, VERSION, XnaError, install, present  # noqa: F401
