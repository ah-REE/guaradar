"""Community road reporting: lifecycle, snapping, image handling, and persistence.

Kept as a package rather than a module because the three concerns have genuinely different
testability needs:

  lifecycle   — pure functions, no I/O at all, testable at any instant with an injected clock
  snapping    — pure geometry over the road graph, no database
  images      — pure pixel work, no database; the byte-storage boundary is in repository.py
  repository  — the only part that touches SQLite, so the only part needing a temp database

This keeps the safety-critical logic (what status a road has, what a photograph may assert)
in code that can be tested exhaustively and instantly.
"""
