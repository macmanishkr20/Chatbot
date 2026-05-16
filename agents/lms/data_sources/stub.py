"""
Stub LMS data source — canned, deterministic responses for dev / CI.

Used when LMS_DATA_SOURCE_KIND=stub (default). Never returns errors so the
full agent pipeline can be exercised without a real backend. All returned
records are clearly marked with ``backend: "stub"`` so accidental
production use is detectable.

To exercise error paths in tests, see ``agents/lms/data_sources/sql.py`` and
``agents/lms/data_sources/http.py`` once they are filled in.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.lms.data_source import LMSDataSource, make_source_block


class StubLMSDataSource(LMSDataSource):
    """In-memory canned LMS responses. Always succeeds."""

    backend_name: str = "stub"

    async def get_leave_balance(
        self,
        employee_id: str,
        leave_type: str | None = None,
    ) -> dict:
        balances = [
            {"leave_type": "Annual",    "entitled": 25.0, "used": 12.5, "remaining": 12.5, "unit": "days"},
            {"leave_type": "Sick",      "entitled": 10.0, "used": 2.0,  "remaining": 8.0,  "unit": "days"},
            {"leave_type": "Casual",    "entitled": 6.0,  "used": 1.0,  "remaining": 5.0,  "unit": "days"},
            {"leave_type": "Paternity", "entitled": 5.0,  "used": 0.0,  "remaining": 5.0,  "unit": "days"},
            {"leave_type": "Maternity", "entitled": 90.0, "used": 0.0,  "remaining": 90.0, "unit": "days"},
        ]
        if leave_type:
            wanted = leave_type.strip().lower()
            balances = [b for b in balances if b["leave_type"].lower() == wanted]
        return {
            "employee_id": employee_id,
            "as_of_year": datetime.now(timezone.utc).year,
            "balances": balances,
            "source": make_source_block(self.backend_name, dataset="canned_v1"),
        }

    async def get_leave_applications(
        self,
        employee_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> dict:
        apps = [
            {"id": "LV-2026-0142", "leave_type": "Annual",   "from": "2026-04-12", "to": "2026-04-16", "days": 5.0, "status": "Approved"},
            {"id": "LV-2026-0099", "leave_type": "Sick",     "from": "2026-02-03", "to": "2026-02-04", "days": 2.0, "status": "Approved"},
            {"id": "LV-2026-0211", "leave_type": "Annual",   "from": "2026-06-01", "to": "2026-06-07", "days": 5.0, "status": "Pending"},
            {"id": "LV-2026-0220", "leave_type": "Casual",   "from": "2026-05-22", "to": "2026-05-22", "days": 1.0, "status": "Approved"},
        ]
        if status:
            wanted = status.strip().lower()
            apps = [a for a in apps if a["status"].lower() == wanted]
        apps = apps[:max(1, limit)]
        return {
            "employee_id": employee_id,
            "applications": apps,
            "source": make_source_block(self.backend_name, dataset="canned_v1"),
        }

    async def get_pending_approvals(self, manager_id: str) -> dict:
        return {
            "manager_id": manager_id,
            "approvals": [
                {"id": "LV-2026-0312", "applicant": "alice.tarek@ae.ey.com",
                 "leave_type": "Annual",   "from": "2026-07-10", "to": "2026-07-17",
                 "days": 6.0, "submitted_at": "2026-05-14T09:21:00Z"},
                {"id": "LV-2026-0318", "applicant": "yusuf.al-amin@sa.ey.com",
                 "leave_type": "Paternity","from": "2026-06-02", "to": "2026-06-06",
                 "days": 5.0, "submitted_at": "2026-05-15T12:04:00Z"},
            ],
            "source": make_source_block(self.backend_name, dataset="canned_v1"),
        }
