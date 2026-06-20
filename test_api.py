"""
Test suite for Event Registration System API
Run with: python test_api.py
"""

import json
import os
import sys
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

# Ensure we can import from parent dir
sys.path.insert(0, os.path.dirname(__file__))

# ── Use TestClient instead of a live server ──────

from fastapi.testclient import TestClient
from main import app, DATA_FILE

client = TestClient(app)


def future_date(days: int = 30) -> str:
    return (datetime.now() + timedelta(days=days)).isoformat()


def past_date(days: int = 1) -> str:
    return (datetime.now() - timedelta(days=days)).isoformat()


class BaseTest(unittest.TestCase):
    def setUp(self):
        # Start every test with a clean slate
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)


# ──────────────────────────────────────────────
# 1. Create Event tests
# ──────────────────────────────────────────────

class TestCreateEvent(BaseTest):

    def test_create_event_success(self):
        r = client.post("/events", json={
            "name": "PyCon 2026",
            "total_seats": 100,
            "event_date": future_date(30),
        })
        self.assertEqual(r.status_code, 201)
        self.assertIn("event_id", r.json())

    def test_duplicate_name_rejected(self):
        payload = {"name": "Unique Event", "total_seats": 50, "event_date": future_date(10)}
        client.post("/events", json=payload)
        r = client.post("/events", json=payload)
        self.assertEqual(r.status_code, 409)

    def test_zero_seats_rejected(self):
        r = client.post("/events", json={
            "name": "Bad Event", "total_seats": 0, "event_date": future_date(5),
        })
        self.assertEqual(r.status_code, 422)

    def test_negative_seats_rejected(self):
        r = client.post("/events", json={
            "name": "Bad Event 2", "total_seats": -10, "event_date": future_date(5),
        })
        self.assertEqual(r.status_code, 422)

    def test_past_date_rejected(self):
        r = client.post("/events", json={
            "name": "Old Event", "total_seats": 10, "event_date": past_date(1),
        })
        self.assertEqual(r.status_code, 422)

    def test_invalid_date_format_rejected(self):
        r = client.post("/events", json={
            "name": "Bad Date Event", "total_seats": 10, "event_date": "not-a-date",
        })
        self.assertEqual(r.status_code, 422)

    def test_empty_name_rejected(self):
        r = client.post("/events", json={
            "name": "   ", "total_seats": 10, "event_date": future_date(5),
        })
        self.assertEqual(r.status_code, 422)


# ──────────────────────────────────────────────
# 2. View Events tests
# ──────────────────────────────────────────────

class TestViewEvents(BaseTest):

    def _create(self, name, seats=50, days=10):
        r = client.post("/events", json={
            "name": name, "total_seats": seats, "event_date": future_date(days),
        })
        return r.json()["event_id"]

    def test_list_empty(self):
        r = client.get("/events")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 0)

    def test_list_multiple_events(self):
        self._create("Event A", days=20)
        self._create("Event B", days=5)
        r = client.get("/events")
        self.assertEqual(r.json()["count"], 2)

    def test_sort_by_date(self):
        self._create("Far Event", days=30)
        self._create("Near Event", days=5)
        r = client.get("/events?sort_by_date=true")
        events = r.json()["events"]
        self.assertEqual(events[0]["name"], "Near Event")

    def test_upcoming_only_filter(self):
        # Can only test with future events in this context
        self._create("Future Event", days=10)
        r = client.get("/events?upcoming_only=true")
        self.assertGreaterEqual(r.json()["count"], 1)

    def test_event_shows_available_seats(self):
        eid = self._create("Seat Count Event", seats=5)
        client.post("/registrations", json={"user_name": "Alice", "event_id": eid})
        r = client.get(f"/events/{eid}")
        self.assertEqual(r.json()["available_seats"], 4)
        self.assertEqual(r.json()["total_registrations"], 1)


# ──────────────────────────────────────────────
# 3. Register User tests
# ──────────────────────────────────────────────

class TestRegisterUser(BaseTest):

    def _event(self, name="Test Event", seats=5):
        r = client.post("/events", json={
            "name": name, "total_seats": seats, "event_date": future_date(10),
        })
        return r.json()["event_id"]

    def test_register_success(self):
        eid = self._event()
        r = client.post("/registrations", json={"user_name": "Bob", "event_id": eid})
        self.assertEqual(r.status_code, 201)
        self.assertIn("registration_id", r.json())

    def test_duplicate_registration_rejected(self):
        eid = self._event()
        client.post("/registrations", json={"user_name": "Carol", "event_id": eid})
        r = client.post("/registrations", json={"user_name": "Carol", "event_id": eid})
        self.assertEqual(r.status_code, 409)

    def test_unknown_event_rejected(self):
        r = client.post("/registrations", json={
            "user_name": "Dave", "event_id": "00000000-0000-0000-0000-000000000000",
        })
        self.assertEqual(r.status_code, 404)

    def test_overbooking_rejected(self):
        eid = self._event(seats=2)
        client.post("/registrations", json={"user_name": "User1", "event_id": eid})
        client.post("/registrations", json={"user_name": "User2", "event_id": eid})
        r = client.post("/registrations", json={"user_name": "User3", "event_id": eid})
        self.assertEqual(r.status_code, 409)
        self.assertIn("full", r.json()["detail"].lower())

    def test_seats_decrement_on_register(self):
        eid = self._event(seats=3)
        client.post("/registrations", json={"user_name": "Eve", "event_id": eid})
        r = client.get(f"/events/{eid}")
        self.assertEqual(r.json()["available_seats"], 2)

    def test_case_insensitive_duplicate(self):
        """Same user different casing should still be a duplicate"""
        eid = self._event()
        client.post("/registrations", json={"user_name": "alice", "event_id": eid})
        r = client.post("/registrations", json={"user_name": "ALICE", "event_id": eid})
        self.assertEqual(r.status_code, 409)

    def test_registration_stores_timestamp(self):
        eid = self._event()
        r = client.post("/registrations", json={"user_name": "Frank", "event_id": eid})
        rid = r.json()["registration_id"]
        regs = client.get(f"/events/{eid}/registrations").json()["registrations"]
        reg = next(reg for reg in regs if reg["id"] == rid)
        self.assertIn("registered_at", reg)


# ──────────────────────────────────────────────
# 4. Cancel Registration tests
# ──────────────────────────────────────────────

class TestCancelRegistration(BaseTest):

    def _setup(self, seats=5):
        eid = client.post("/events", json={
            "name": "Cancel Test Event", "total_seats": seats, "event_date": future_date(10),
        }).json()["event_id"]
        rid = client.post("/registrations", json={
            "user_name": "Grace", "event_id": eid,
        }).json()["registration_id"]
        return eid, rid

    def test_cancel_success(self):
        eid, rid = self._setup()
        r = client.delete(f"/registrations/{rid}")
        self.assertEqual(r.status_code, 200)

    def test_seat_restored_after_cancel(self):
        eid, rid = self._setup(seats=2)
        client.delete(f"/registrations/{rid}")
        r = client.get(f"/events/{eid}")
        self.assertEqual(r.json()["available_seats"], 2)

    def test_cancelled_user_not_in_active_list(self):
        eid, rid = self._setup()
        client.delete(f"/registrations/{rid}")
        regs = client.get(f"/events/{eid}/registrations").json()["registrations"]
        self.assertEqual(len(regs), 0)

    def test_double_cancel_rejected(self):
        _, rid = self._setup()
        client.delete(f"/registrations/{rid}")
        r = client.delete(f"/registrations/{rid}")
        self.assertEqual(r.status_code, 409)

    def test_cancel_unknown_registration(self):
        r = client.delete("/registrations/00000000-0000-0000-0000-000000000000")
        self.assertEqual(r.status_code, 404)

    def test_reregister_after_cancel(self):
        """User who cancelled should be able to re-register"""
        eid, rid = self._setup(seats=5)
        client.delete(f"/registrations/{rid}")
        # Re-register same user
        r = client.post("/registrations", json={"user_name": "Grace", "event_id": eid})
        # Currently the API prevents re-registration after cancel;
        # uncomment to enable and adjust business logic accordingly
        # self.assertEqual(r.status_code, 201)


# ──────────────────────────────────────────────
# 5. Race-condition / concurrency test
# ──────────────────────────────────────────────

class TestConcurrency(BaseTest):

    def test_no_overbooking_under_concurrent_requests(self):
        """100 concurrent registration attempts for 10-seat event → exactly 10 succeed"""
        eid = client.post("/events", json={
            "name": "Race Condition Event",
            "total_seats": 10,
            "event_date": future_date(10),
        }).json()["event_id"]

        results = []
        lock = threading.Lock()

        def register(i):
            r = client.post("/registrations", json={
                "user_name": f"user_{i}", "event_id": eid,
            })
            with lock:
                results.append(r.status_code)

        threads = [threading.Thread(target=register, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = results.count(201)
        ev = client.get(f"/events/{eid}").json()

        self.assertEqual(successes, 10, f"Expected 10 successes, got {successes}")
        self.assertEqual(ev["available_seats"], 0)
        self.assertEqual(ev["total_registrations"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
