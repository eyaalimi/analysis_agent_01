"""
agents/agent_storage/agent.py
Storage Agent — persists the full procurement pipeline data to PostgreSQL.

Unlike other agents, this one does NOT use an LLM.
It's a pure data layer that the orchestrator calls at each pipeline stage.

Input  : Outputs from Agent 1, 2, 3 (dicts/dataclasses)
Output : Database IDs for stored records
"""
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from logger import get_logger
from agents.agent_storage.tools import StorageTools

logger = get_logger(__name__)


@dataclass
class StorageResult:
    """Summary of what was stored in a single pipeline run."""
    request_id: str
    suppliers_stored: int
    rfqs_stored: int
    offers_stored: int
    status: str


class StorageAgent:
    """
    Manages persistence for the entire procurement pipeline.
    Called by the orchestrator after each agent completes.
    """

    def __init__(self, database_url: str = None):
        self._tools = StorageTools(database_url)

    # ── Stage 1: Store procurement request (Agent 1 output) ──────────────

    def store_request(self, procurement_spec: dict) -> str:
        """
        Store the validated procurement spec from Agent 1.
        Returns the request_id for use in subsequent stages.
        """
        request_id = self._tools.store_request(procurement_spec)
        self._tools.update_request_status(request_id, "analyzing")
        return request_id

    # ── Stage 2: Store suppliers (Agent 2 output) ────────────────────────

    def store_suppliers(self, request_id: str, supplier_list: dict) -> dict:
        """
        Store the supplier list from Agent 2.
        Returns a mapping of supplier_email -> supplier_db_id
        for use in later stages.
        """
        stored = self._tools.store_suppliers(request_id, supplier_list)
        self._tools.update_request_status(request_id, "sourcing")

        # Build email -> db_id mapping
        supplier_map = {}
        suppliers = supplier_list.get("suppliers", [])
        for (name, db_id), s in zip(stored, suppliers):
            email = s.get("email", "")
            if email:
                supplier_map[email] = db_id

        return supplier_map

    # ── Stage 3: Store RFQs (Agent 3 Phase 1 output) ────────────────────

    def store_rfqs(self, request_id: str, rfq_records: list, supplier_map: dict) -> dict:
        """
        Store RFQ sending records from Agent 3.
        Returns a mapping of supplier_email -> rfq_db_id.
        """
        # Convert dataclasses to dicts if needed
        rfq_dicts = []
        for r in rfq_records:
            if hasattr(r, "__dict__") and not isinstance(r, dict):
                rfq_dicts.append(asdict(r))
            else:
                rfq_dicts.append(r)

        stored = self._tools.store_rfqs(request_id, rfq_dicts, supplier_map)
        self._tools.update_request_status(request_id, "rfqs_sent")

        # Build email -> rfq_db_id mapping
        rfq_map = {}
        for (name, rfq_db_id), r in zip(stored, rfq_dicts):
            email = r.get("supplier_email", "")
            if email:
                rfq_map[email] = rfq_db_id

        return rfq_map

    # ── Stage 4: Store offers (Agent 3 Phase 2 output) ──────────────────

    def store_offers(
        self, request_id: str, offers: list,
        supplier_map: dict, rfq_map: dict,
    ) -> list:
        """
        Store parsed supplier offers.
        Returns list of (supplier_name, offer_db_id) tuples.
        """
        offer_dicts = []
        for o in offers:
            if hasattr(o, "__dict__") and not isinstance(o, dict):
                offer_dicts.append(asdict(o))
            else:
                offer_dicts.append(o)

        stored = self._tools.store_offers(request_id, offer_dicts, supplier_map, rfq_map)
        self._tools.update_request_status(request_id, "offers_received")
        return stored

    # ── Full pipeline store ─────────────────────────────────────────────

    def store_full_pipeline(
        self,
        procurement_spec: dict,
        supplier_list: dict,
        rfq_records: list,
        offers: list,
    ) -> StorageResult:
        """
        Store all pipeline data in one call.
        Used when replaying or batch-importing results.
        """
        request_id = self.store_request(procurement_spec)

        supplier_map = self.store_suppliers(request_id, supplier_list)

        rfq_map = self.store_rfqs(request_id, rfq_records, supplier_map)

        stored_offers = self.store_offers(request_id, offers, supplier_map, rfq_map)

        return StorageResult(
            request_id=request_id,
            suppliers_stored=len(supplier_map),
            rfqs_stored=len(rfq_map),
            offers_stored=len(stored_offers),
            status="offers_received",
        )

    # ── Queries ─────────────────────────────────────────────────────────

    def get_request(self, request_id: str) -> Optional[dict]:
        return self._tools.get_request(request_id)

    def get_offers(self, request_id: str) -> list:
        return self._tools.get_offers_for_request(request_id)

    def update_status(self, request_id: str, status: str):
        self._tools.update_request_status(request_id, status)
