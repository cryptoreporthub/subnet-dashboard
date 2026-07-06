"""Subnet Dashboard server package.

Imports the app from the original monolith (server_original.py) which has
all routes, static mounts, and health endpoints intact.
This bypasses the broken modular split.
"""
from server_original import app  # noqa: F401
