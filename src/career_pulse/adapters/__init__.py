"""
CareerPulse ATS Adapters and Detection Suite.
"""

from typing import Dict, Type
from .base import BaseATSAdapter
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .ashby import AshbyAdapter
from .workday import WorkdayAdapter
from .fallback import FallbackScraper
from .detector import ATSDetector

ADAPTER_REGISTRY: Dict[str, Type[BaseATSAdapter]] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "workday": WorkdayAdapter,
    "custom": FallbackScraper,
    "playwright": FallbackScraper,
}


def get_adapter(provider: str, **kwargs) -> BaseATSAdapter:
    """Factory helper to instantiate the appropriate adapter for a given provider."""
    prov_key = provider.lower().strip()
    adapter_cls = ADAPTER_REGISTRY.get(prov_key, FallbackScraper)
    return adapter_cls(**kwargs)


__all__ = [
    "BaseATSAdapter",
    "GreenhouseAdapter",
    "LeverAdapter",
    "AshbyAdapter",
    "WorkdayAdapter",
    "FallbackScraper",
    "ATSDetector",
    "ADAPTER_REGISTRY",
    "get_adapter",
]
