"""Code modules for the data/learning layer.

Runtime data files live in ``data/`` (a Fly.io persistent volume mount point
in production), so the Python modules that operate on them live here in
``datastore/`` to avoid being shadowed when ``data/`` is mounted as a volume.
"""
