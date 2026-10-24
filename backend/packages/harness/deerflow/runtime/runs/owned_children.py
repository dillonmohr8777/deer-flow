"""Host-only handles proving ordinary delegated execution has actually drained."""

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

OWNED_CHILDREN_CONTEXT_KEY = "__run_owned_children"


@dataclass
class OwnedChild:
    cancel: Callable[[], None]
    completed: threading.Event = field(default_factory=threading.Event)
    cleanup_started: threading.Event = field(default_factory=threading.Event)
    entered: bool = False
    execution_entered: bool = False
    cleanup_reached: bool = False
    cleanup_failed: bool = False
    confirmed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def enter(self) -> bool:
        with self._lock:
            if self.completed.is_set():
                return False
            self.entered = True
            return True

    def cancel_before_entry(self) -> None:
        with self._lock:
            if not self.entered:
                self.confirmed = True
                self.completed.set()

    def finish(self) -> None:
        with self._lock:
            self.confirmed = not self.execution_entered or (self.cleanup_reached and not self.cleanup_failed)
            self.completed.set()


class OwnedRunChildren:
    def __init__(self) -> None:
        self._children: list[OwnedChild] = []
        self._lock = threading.Lock()
        self._cancelling = False

    def register(self, child: OwnedChild) -> None:
        with self._lock:
            self._children.append(child)
            cancelling = self._cancelling
        if cancelling:
            child.cancel_before_entry()
            child.cancel()

    async def drain(self, abort_event: asyncio.Event) -> None:
        cancelled: set[int] = set()
        while True:
            with self._lock:
                self._cancelling = self._cancelling or abort_event.is_set()
                children = list(self._children)
                cancelling = self._cancelling
            for child in children:
                if cancelling and not child.completed.is_set() and not child.cleanup_started.is_set() and id(child) not in cancelled:
                    cancelled.add(id(child))
                    child.cancel()
            if all(child.completed.is_set() for child in children):
                if any(not child.confirmed for child in children):
                    raise RuntimeError("Owned child cleanup is unconfirmed; original run admission must remain held")
                return
            # Waits on actual cross-loop completion events, never Future.done().
            await asyncio.sleep(0.01)
