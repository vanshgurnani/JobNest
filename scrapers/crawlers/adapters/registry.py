"""Provider adapter registry and capability-based selection."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Callable

from scrapers.crawlers.adapters.base import CareerPortalAdapter
from scrapers.crawlers.adapters.legacy import ProviderAdapter, UniversalAdapter
from scrapers.crawlers.contracts import DetectionResult


class AdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], CareerPortalAdapter]] = {}

    def register(self, provider: str, factory: Callable[[], CareerPortalAdapter] | CareerPortalAdapter) -> None:
        if isinstance(factory, CareerPortalAdapter):
            self._factories[provider] = lambda factory=factory: factory
        else:
            self._factories[provider] = factory

    def get(self, provider: str) -> CareerPortalAdapter:
        factory = self._factories.get(provider) or self._factories["universal"]
        return factory()

    def select(self, detection: DetectionResult | dict) -> CareerPortalAdapter:
        provider = detection.provider if isinstance(detection, DetectionResult) else str(detection.get("provider", "unknown"))
        return self.get(provider if provider in self._factories else "universal")

    def providers(self) -> list[str]:
        return sorted(self._factories)

    @classmethod
    def default(cls) -> "AdapterRegistry":
        registry = cls()
        for provider in (
            "greenhouse", "lever", "ashby", "workday", "smartrecruiters", "icims", "workable",
            "jobvite", "bamboohr", "recruitee", "teamtailor", "pinpoint", "successfactors", "taleo",
            "custom_api",
        ):
            registry.register(provider, lambda provider=provider: ProviderAdapter(provider))
        registry.register("universal", UniversalAdapter)
        return registry


default_registry = AdapterRegistry.default()
