# Event Registration System API
**Innovaxel Backend Assessment – Summer Intern**

A production-quality REST API built with **FastAPI** and **Python**, featuring persistent JSON storage, race-condition protection, and a full test suite.

---

## Tech Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Language | Python 3.10+ | Expressive, fast prototyping |
| Framework | FastAPI | Auto-docs, async-ready, Pydantic validation |
| Storage | JSON file (`data.json`) | Simple, portable, no setup |
| Concurrency | `threading.Lock` | Prevents overbooking race conditions |
| Testing | `unittest` + `TestClient` | Zero external dependencies |

---

## Setup

```bash
git clone <repo-url>
cd event-registration
pip install -r requirements.txt
```

---

## Run

```bash
uvicorn main:app --reload
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## API Reference

### Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/events` | Create a new event |
| `GET` | `/events` | List all events (filter & sort supported) |
| `GET` | `/events/{id}` | Get a single event |
| `GET` | `/events/{id}/registrations` | List active registrations for an event |

#### Create Event – `POST /events`

```json
{
  "name": "PyCon 2026",
  "total_seats": 100,
  "event_date": "2026-09-15T10:00:00"
}
```

**Validation rules:**
- `name` must be unique (case-insensitive)
- `total_seats` must be > 0
- `event_date` must be in the future (ISO-8601)

#### List Events – `GET /events`

Query params:
- `upcoming_only=true` – show only events with a future date
- `sort_by_date=true` (default) – sort ascending by event date

---

### Registrations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/registrations` | Register a user for an event |
| `DELETE` | `/registrations/{id}` | Cancel a registration |

#### Register – `POST /registrations`

```json
{
  "user_name": "Alice",
  "event_id": "<uuid>"
}
```

**Rules:**
- Event must exist
- Event must have available seats
- Same user cannot register twice for the same event (409)
- Registration stores a timestamp

#### Cancel – `DELETE /registrations/{id}`

- Releases the seat (available_seats + 1)
- Cancelled registrations are hidden from active lists
- Double-cancelling returns 409

---

## Key Design Decisions

### Race Condition Prevention
All write operations (create event, register, cancel) are wrapped in a `threading.Lock`. This ensures that even under concurrent load, seat counts remain consistent and overbooking is impossible.

```python
with _lock:
    data = _load()
    # ... mutate atomically ...
    _save(data)
```

### Duplicate Request Safety
Duplicate registrations are caught by scanning existing registrations inside the same lock, before decrementing the seat counter. This prevents TOCTOU bugs.

### Correct Seat Count
`available_seats` is always `total_seats – active_registrations`. It is decremented on register and incremented on cancel, capped at `total_seats`.

### Data Model

```
events
  id            UUID
  name          str (unique)
  total_seats   int > 0
  available_seats int
  event_date    ISO-8601 datetime (future)
  created_at    ISO-8601 datetime

registrations
  id            UUID
  event_id      FK → events.id
  user_name     str
  registered_at ISO-8601 datetime
  status        "active" | "cancelled"
  cancelled_at  ISO-8601 datetime (optional)
```

---

## Run Tests

```bash
python test_api.py
```

Covers: validation rules, duplicate prevention, overbooking, cancellation, seat restoration, and a **100-thread concurrency stress test** that verifies exactly 10 seats are filled for a 10-seat event.

---

## Error Responses

All errors follow a consistent shape:

```json
{ "detail": "Human-readable error message" }
```

| Code | Meaning |
|------|---------|
| 201 | Created |
| 200 | OK |
| 404 | Resource not found |
| 409 | Conflict (duplicate, full event, already cancelled) |
| 422 | Validation error (bad input) |
