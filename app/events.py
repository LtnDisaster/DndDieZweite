"""Game events: plain facts about things that HAVE HAPPENED.

An event is a small plain dict (JSON-serializable, transport-free):

    {"type": "door_opened", "room_id": 3, "actor_id": 7,
     "target_id": None, "data": {"x": 10, "y": 6, "dir": "v", "locked": False}}

Rules (D52):

* A game operation changes the authoritative world FIRST, then emits the
  event. The event is never the place state lives — dropping every event must
  never lose a door, a quest or a trap result.
* Events never carry WebSocket/FastAPI/browser objects; they are domain data.
* Listeners are synchronous, fast and side-effect-free with respect to game
  state. A raising listener must never break the emitting operation.
* This is NOT an event bus/queue/event-sourcing platform. It is the seam where
  a future trigger engine will live:

      GameEvent -> trigger condition matches -> CALL A GAME OPERATION
      (e.g. enter_area("crypt") -> CompleteObjective(quest, objective))

  Triggers must call the same pure operations humans use (app.quests, …) —
  never a WebSocket handler and never a faked client message (D49).
"""
import collections
import logging

log = logging.getLogger("vtt.events")

MAX_RECENT = 256
# Ring of the last emitted events — diagnostics/tests only, never game state.
recent: collections.deque = collections.deque(maxlen=MAX_RECENT)

_listeners: dict[str, list] = {}


def make(event_type, *, room_id=None, actor_id=None, target_id=None, **data) -> dict:
    """Build an event dict. `data` must stay JSON-serializable domain data."""
    return {"type": str(event_type), "room_id": room_id, "actor_id": actor_id,
            "target_id": target_id, "data": data}


def subscribe(event_type, fn):
    """Register a synchronous listener for one event type. Returns fn."""
    _listeners.setdefault(str(event_type), []).append(fn)
    return fn


def unsubscribe(event_type, fn=None):
    if fn is None:
        _listeners.pop(str(event_type), None)
        return
    lst = _listeners.get(str(event_type)) or []
    if fn in lst:
        lst.remove(fn)


def emit(event: dict) -> dict:
    """Record an already-happened fact and notify listeners. Never raises."""
    recent.append(event)
    for fn in list(_listeners.get(event.get("type") or "", ())):
        try:
            fn(event)
        except Exception:
            log.exception("event listener failed for %s", event.get("type"))
    return event


def clear():
    """Test isolation: drop the ring and any listeners registered at runtime."""
    recent.clear()
    _listeners.clear()
