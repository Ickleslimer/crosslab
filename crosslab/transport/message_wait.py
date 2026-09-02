"""
Long-poll message wait registry for CrossLab A2A nodes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Set

from crosslab.protocol.models import MessageEnvelope


def message_matches_filters(
    envelope: MessageEnvelope,
    *,
    since_id: Optional[str],
    actions: Optional[Set[str]],
    exclude_agent_id: Optional[str],
    ordered_messages: List[MessageEnvelope],
) -> bool:
    """Return True if envelope satisfies waiter filters."""
    origin = envelope.origin_sender_id or envelope.sender_id
    if exclude_agent_id and (envelope.sender_id == exclude_agent_id or origin == exclude_agent_id):
        return False

    action_val = envelope.action.value if hasattr(envelope.action, "value") else str(envelope.action)
    if actions and action_val not in actions:
        return False

    if since_id:
        since_seen = False
        after_since = False
        for msg in ordered_messages:
            if msg.message_id == since_id:
                since_seen = True
                continue
            if since_seen:
                if msg.message_id == envelope.message_id:
                    after_since = True
                    break
        if since_seen and not after_since:
            return False
        if not since_seen:
            # Unknown since_id — accept any matching message
            pass

    return True


@dataclass
class MessageWaiter:
    since_id: Optional[str]
    actions: Optional[Set[str]]
    exclude_agent_id: Optional[str]
    future: asyncio.Future = field(repr=False)
    ordered_messages: List[MessageEnvelope] = field(default_factory=list)


class MessageWaitRegistry:
    def __init__(self) -> None:
        self._waiters: List[MessageWaiter] = []

    def register(self, waiter: MessageWaiter) -> None:
        self._waiters.append(waiter)

    def unregister(self, waiter: MessageWaiter) -> None:
        if waiter in self._waiters:
            self._waiters.remove(waiter)

    def notify(self, envelope: MessageEnvelope) -> None:
        for waiter in list(self._waiters):
            if waiter.future.done():
                self.unregister(waiter)
                continue
            if message_matches_filters(
                envelope,
                since_id=waiter.since_id,
                actions=waiter.actions,
                exclude_agent_id=waiter.exclude_agent_id,
                ordered_messages=waiter.ordered_messages,
            ):
                waiter.future.set_result(envelope)
                self.unregister(waiter)

    def cancel_all(self) -> None:
        for waiter in list(self._waiters):
            if not waiter.future.done():
                waiter.future.cancel()
            self.unregister(waiter)
