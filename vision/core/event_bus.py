"""
Asynchronous Pub/Sub Event Bus for non-blocking communication across VISION modules.
"""

import asyncio
from typing import Callable, Coroutine, Dict, List, Any
from vision.logger import logger


class EventBus:
    def __init__(self):
        self._listeners: Dict[str, List[Callable[[Any], Coroutine[Any, Any, None]]]] = {}
        self._sync_listeners: Dict[str, List[Callable[[Any], None]]] = {}

    def subscribe(self, topic: str, callback: Callable[[Any], Coroutine[Any, Any, None]]):
        """Subscribe an async coroutine to a specific topic."""
        if topic not in self._listeners:
            self._listeners[topic] = []
        if callback not in self._listeners[topic]:
            self._listeners[topic].append(callback)
            logger.debug(f"[EventBus] Subscribed async listener to '{topic}'")

    def subscribe_sync(self, topic: str, callback: Callable[[Any], None]):
        """Subscribe a synchronous function to a specific topic."""
        if topic not in self._sync_listeners:
            self._sync_listeners[topic] = []
        if callback not in self._sync_listeners[topic]:
            self._sync_listeners[topic].append(callback)
            logger.debug(f"[EventBus] Subscribed sync listener to '{topic}'")

    def unsubscribe(self, topic: str, callback: Callable):
        """Unsubscribe a listener from a topic."""
        if topic in self._listeners and callback in self._listeners[topic]:
            self._listeners[topic].remove(callback)
        if topic in self._sync_listeners and callback in self._sync_listeners[topic]:
            self._sync_listeners[topic].remove(callback)

    async def publish(self, topic: str, data: Any = None):
        """Publish an event to all subscribers of a topic concurrently."""
        logger.debug(f"[EventBus] Publishing event: {topic}")
        tasks = []

        # Execute async listeners (snapshot: handlers may (un)subscribe during dispatch)
        if topic in self._listeners:
            for cb in list(self._listeners[topic]):
                tasks.append(asyncio.create_task(self._safe_execute_async(cb, data, topic)))

        # Execute sync listeners (snapshot for the same reason)
        if topic in self._sync_listeners:
            for cb in list(self._sync_listeners[topic]):
                try:
                    cb(data)
                except Exception as e:
                    logger.error(f"[EventBus] Error in sync handler for '{topic}': {e}")

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_execute_async(self, callback: Callable, data: Any, topic: str):
        try:
            await callback(data)
        except Exception as e:
            logger.error(f"[EventBus] Error in async handler for '{topic}': {e}")


# Global event bus singleton
event_bus = EventBus()
