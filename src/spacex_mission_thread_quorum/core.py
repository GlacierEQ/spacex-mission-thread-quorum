"""Autonomous Systems Engineering — Core Module"""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass(frozen=True)
class OperationReceipt:
    """Immutable receipt for a verified operation."""
    operation_id: str
    operator: str
    action: str
    result: str
    timestamp: float = field(default_factory=time.time)

    @property
    def sha256(self) -> str:
        raw = f"{{self.operation_id}}:{{self.action}}:{{self.result}}:{{self.timestamp}}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


class ContractEnforcer:
    """Enforces operational contracts with receipt chains."""

    def __init__(self):
        self._receipts: list[OperationReceipt] = []
        self._preconditions: dict[str, callable] = {{}}

    def register_precondition(self, action: str, check: callable) -> None:
        self._preconditions[action] = check

    def execute(self, operation_id: str, operator: str, action: str, context: Any = None) -> OperationReceipt:
        if action in self._preconditions:
            if not self._preconditions[action](context):
                raise ValueError(f"Precondition failed for {{action}}")
        receipt = OperationReceipt(operation_id, operator, action, "COMPLETED")
        self._receipts.append(receipt)
        return receipt

    @property
    def receipt_chain(self) -> list[OperationReceipt]:
        return list(self._receipts)

    def verify_chain_integrity(self) -> bool:
        for i, r in enumerate(self._receipts):
            if i > 0 and r.timestamp < self._receipts[i - 1].timestamp:
                return False
        return True

