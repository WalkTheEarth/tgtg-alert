"""Self-hosted Too Good To Go availability watcher.

Polls the (unofficial) TGTG API for bags near a location, matches them against
user-defined watch rules, and pushes a notification when a watched bag makes a
0 -> >0 stock transition.
"""

__version__ = "0.1.0"
