"""Scheduled booking execution primitives.

The saved manual queue remains the user's editable intent. This package stores
separate, immutable, per-credential execution snapshots and runs them only from
the explicitly started worker process.
"""
