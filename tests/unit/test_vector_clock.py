"""
Unit tests for VectorClock.
These test the core causal ordering logic — no storage, no network.
The vector clock is the heart of conflict detection; it must be correct.
"""
import pytest
from agentskein.protocol.types import VectorClock


class TestVectorClockOrdering:

    def test_empty_clocks_do_not_conflict(self):
        """Two agents that have never seen each other don't conflict (both empty)."""
        a = VectorClock()
        b = VectorClock()
        assert not a.concurrent_with(b)

    def test_dominates_when_strictly_greater(self):
        """If A has seen everything B has seen plus more, A dominates B."""
        a = VectorClock(clocks={"agent-A": 3, "agent-B": 2})
        b = VectorClock(clocks={"agent-A": 1, "agent-B": 2})
        assert a.dominates(b)
        assert not b.dominates(a)

    def test_concurrent_writes_detected(self):
        """
        Two agents that both incremented without seeing each other's
        updates are concurrent — this is the conflict scenario.
        """
        clock_a = VectorClock(clocks={"agent-A": 1})
        clock_b = VectorClock(clocks={"agent-B": 1})
        assert clock_a.concurrent_with(clock_b)
        assert clock_b.concurrent_with(clock_a)

    def test_causal_sequence_not_concurrent(self):
        """
        Agent-B that read Agent-A's write before writing is NOT concurrent.
        This is a causally ordered sequence — no conflict.
        """
        clock_after_a = VectorClock(clocks={"agent-A": 1})
        clock_after_b = clock_after_a.increment("agent-B")
        assert not clock_after_b.concurrent_with(clock_after_a)
        assert clock_after_b.dominates(clock_after_a)

    def test_increment_creates_new_clock(self):
        """Increment must return a new object (immutability)."""
        original = VectorClock(clocks={"agent-A": 1})
        incremented = original.increment("agent-A")
        assert incremented.clocks["agent-A"] == 2
        assert original.clocks["agent-A"] == 1   # original unchanged

    def test_merge_takes_component_wise_max(self):
        """Merge of two clocks takes max at each component."""
        a = VectorClock(clocks={"agent-A": 3, "agent-B": 1})
        b = VectorClock(clocks={"agent-A": 1, "agent-B": 5, "agent-C": 2})
        merged = a.merge(b)
        assert merged.clocks == {"agent-A": 3, "agent-B": 5, "agent-C": 2}

    def test_three_way_conflict_all_concurrent(self):
        """Three agents all writing independently — all pairs concurrent."""
        clock_a = VectorClock(clocks={"agent-A": 1})
        clock_b = VectorClock(clocks={"agent-B": 1})
        clock_c = VectorClock(clocks={"agent-C": 1})
        assert clock_a.concurrent_with(clock_b)
        assert clock_b.concurrent_with(clock_c)
        assert clock_a.concurrent_with(clock_c)

    def test_new_agent_first_write(self):
        """An agent writing for the first time starts at count 1."""
        clock = VectorClock()
        incremented = clock.increment("new-agent")
        assert incremented.clocks["new-agent"] == 1

    def test_equal_clocks_do_not_dominate_each_other(self):
        """Equal clocks: A dominates B and B dominates A (both equal)."""
        a = VectorClock(clocks={"agent-A": 2})
        b = VectorClock(clocks={"agent-A": 2})
        assert a.dominates(b)
        assert b.dominates(a)
        assert not a.concurrent_with(b)
