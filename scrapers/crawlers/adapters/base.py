"""Adapter interfaces. Provider implementations stay behind this boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from scrapers.crawlers.contracts import DetectionResult, JobReference, PortalContext, RawJob


class CareerPortalAdapter(ABC):
    name = "unknown"

    @abstractmethod
    async def detect(self, context: PortalContext) -> DetectionResult:
        raise NotImplementedError

    @abstractmethod
    async def discover_jobs(self, context: PortalContext) -> AsyncIterator[JobReference]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_job(self, reference: JobReference, context: PortalContext) -> RawJob:
        raise NotImplementedError

    @abstractmethod
    async def normalize(self, raw_job: RawJob, context: PortalContext) -> dict:
        raise NotImplementedError
