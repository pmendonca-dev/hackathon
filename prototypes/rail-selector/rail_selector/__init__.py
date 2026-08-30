"""Deterministic, non-integrated rail selection prototype."""

from .models import RailSelectionRequest, RailSelectionResult
from .selector import select_rail

__all__ = ["RailSelectionRequest", "RailSelectionResult", "select_rail"]
