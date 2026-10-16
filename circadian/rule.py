"""Fire rules. D13 for command failures. D12's z > 3 remains for re-reads and loops."""

Z_LIMIT = 3.0
MIN_EVENTS = 4
COMMAND_FAILURES_TO_FIRE = 3
LOOP_LENGTHS = (2, 3, 4)
# Larger z wins. Repeated failures use a count, not this order.
RATE_BEHAVIORS = ("reread", "loop")
