"""
agents/agent_communication/__init__.py
Communication Agent package — RFQ generation, sending, monitoring, reminders, offer parsing.
"""
from agents.agent_communication.agent import (
    CommunicationAgent,
    RFQRecord,
    SupplierOffer,
    CommunicationResult,
)

__all__ = ["CommunicationAgent", "RFQRecord", "SupplierOffer", "CommunicationResult"]
