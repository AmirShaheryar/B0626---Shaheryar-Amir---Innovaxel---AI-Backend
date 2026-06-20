"""
Event Registration System API
Innovaxel Backend Assessment – Summer Intern
"""

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
import threading
import json
import os
import uuid

# ──────────────────────────────────────────────
# Storage helpers (JSON-file persistence)
# ──────────────────────────────────────────────

DATA_FILE = "data.json"
_lock = threading.Lock()          # prevents race conditions / overbooking


def _load() -> dict:
    if not os.path.exists(DATA_FILE):
        return {"events": {}, "registrations": {}}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ──────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────

class EventCreate(BaseModel):
    name: str
    total_seats: int
    event_date: str          # ISO-8601  e.g. "2025-12-31T18:00:00"

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Event name cannot be empty")
        return v

    @field_validator("total_seats")
    @classmethod
    def seats_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Total seats must be greater than 0")
        return v

    @field_validator("event_date")
    @classmethod
    def date_in_future(cls, v: str) -> str:
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("event_date must be ISO-8601 format, e.g. 2025-12-31T18:00:00")
        if dt <= datetime.now():
            raise ValueError("Event date must be in the future")
        return v


class RegistrationCreate(BaseModel):
    user_name: str
    event_id: str

    @field_validator("user_name")
    @classmethod
    def user_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_name cannot be empty")
        return v


# ──────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────

app = FastAPI(
    title="Event Registration System",
    description="Innovaxel Backend Assessment – Summer Intern",
    version="1.0.0",
)


# ── 1. Create Event ────────────────────────────

@app.post("/events", status_code=201, summary="Create a new event")
def create_event(body: EventCreate):
    with _lock:
        data = _load()

        # Uniqueness check
        for ev in data["events"].values():
            if ev["name"].lower() == body.name.lower():
                raise HTTPException(
                    status_code=409,
                    detail=f"An event named '{body.name}' already exists."
                )

        event_id = str(uuid.uuid4())
        data["events"][event_id] = {
            "id": event_id,
            "name": body.name,
            "total_seats": body.total_seats,
            "available_seats": body.total_seats,
            "event_date": body.event_date,
            "created_at": datetime.now().isoformat(),
        }
        _save(data)

    return {"message": "Event created successfully", "event_id": event_id}


# ── 2. View Events ─────────────────────────────

@app.get("/events", summary="List all events")
def list_events(
    upcoming_only: bool = Query(False, description="Filter to future events only"),
    sort_by_date: bool = Query(True,  description="Sort events by date ascending"),
):
    data = _load()
    events = list(data["events"].values())

    now = datetime.now()

    if upcoming_only:
        events = [e for e in events if datetime.fromisoformat(e["event_date"]) > now]

    if sort_by_date:
        events.sort(key=lambda e: e["event_date"])

    # Annotate with total registration count
    for ev in events:
        ev["total_registrations"] = sum(
            1 for r in data["registrations"].values()
            if r["event_id"] == ev["id"] and r["status"] == "active"
        )

    return {"events": events, "count": len(events)}


# ── Get single event ───────────────────────────

@app.get("/events/{event_id}", summary="Get event details")
def get_event(event_id: str):
    data = _load()
    ev = data["events"].get(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    ev["total_registrations"] = sum(
        1 for r in data["registrations"].values()
        if r["event_id"] == event_id and r["status"] == "active"
    )
    return ev


# ── 3. Register User for Event ─────────────────

@app.post("/registrations", status_code=201, summary="Register a user for an event")
def register_user(body: RegistrationCreate):
    with _lock:                      # ← atomic: prevents double-booking
        data = _load()

        ev = data["events"].get(body.event_id)
        if not ev:
            raise HTTPException(status_code=404, detail="Event not found")

        # Idempotency / duplicate check
        for reg in data["registrations"].values():
            if (
                reg["event_id"] == body.event_id
                and reg["user_name"].lower() == body.user_name.lower()
            ):
                if reg["status"] == "active":
                    raise HTTPException(
                        status_code=409,
                        detail="User is already registered for this event."
                    )
                # If previously cancelled, allow re-registration (fall through)
                break

        # Seat availability check (re-read inside lock)
        if ev["available_seats"] <= 0:
            raise HTTPException(
                status_code=409,
                detail="No seats available. The event is full."
            )

        # Create registration
        reg_id = str(uuid.uuid4())
        data["registrations"][reg_id] = {
            "id": reg_id,
            "event_id": body.event_id,
            "user_name": body.user_name,
            "registered_at": datetime.now().isoformat(),
            "status": "active",
        }
        ev["available_seats"] -= 1
        _save(data)

    return {"message": "Registration successful", "registration_id": reg_id}


# ── 4. Cancel Registration ─────────────────────

@app.delete("/registrations/{registration_id}", summary="Cancel a registration")
def cancel_registration(registration_id: str):
    with _lock:
        data = _load()

        reg = data["registrations"].get(registration_id)
        if not reg:
            raise HTTPException(status_code=404, detail="Registration not found")

        if reg["status"] == "cancelled":
            raise HTTPException(
                status_code=409,
                detail="Registration is already cancelled."
            )

        # Free the seat
        ev = data["events"].get(reg["event_id"])
        if ev:
            ev["available_seats"] = min(ev["available_seats"] + 1, ev["total_seats"])

        reg["status"] = "cancelled"
        reg["cancelled_at"] = datetime.now().isoformat()
        _save(data)

    return {"message": "Registration cancelled successfully"}


# ── List registrations for an event ───────────

@app.get("/events/{event_id}/registrations", summary="View active registrations for an event")
def event_registrations(event_id: str):
    data = _load()

    if event_id not in data["events"]:
        raise HTTPException(status_code=404, detail="Event not found")

    active = [
        r for r in data["registrations"].values()
        if r["event_id"] == event_id and r["status"] == "active"
    ]
    return {"event_id": event_id, "registrations": active, "count": len(active)}
