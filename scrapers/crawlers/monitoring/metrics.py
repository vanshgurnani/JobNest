from __future__ import annotations

import time
from collections import defaultdict
from typing import Any


class ScrapeMetrics:
    def __init__(self) -> None:
        self._attempts: dict[str, int] = defaultdict(int)
        self._successes: dict[str, int] = defaultdict(int)
        self._failures: dict[str, int] = defaultdict(int)
        self._total_jobs: dict[str, int] = defaultdict(int)
        self._response_times: dict[str, list[float]] = defaultdict(list)
        self._strategies: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record_attempt(self, company: str) -> None:
        self._attempts[company] += 1

    def record_success(self, company: str, jobs_count: int, strategy: str = "", duration: float = 0.0) -> None:
        self._successes[company] += 1
        self._total_jobs[company] += jobs_count
        if strategy:
            self._strategies[company][strategy] += 1
        if duration > 0:
            self._response_times[company].append(duration)

    def record_failure(self, company: str, strategy: str = "") -> None:
        self._failures[company] += 1
        if strategy:
            self._strategies[company][strategy] += 1

    def summary(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        all_companies = set(self._attempts) | set(self._successes) | set(self._failures)
        for c in sorted(all_companies):
            times = self._response_times.get(c, [])
            result[c] = {
                "attempts": self._attempts.get(c, 0),
                "successes": self._successes.get(c, 0),
                "failures": self._failures.get(c, 0),
                "total_jobs": self._total_jobs.get(c, 0),
                "avg_response_time": round(sum(times) / len(times), 2) if times else 0.0,
                "strategies": dict(self._strategies.get(c, {})),
            }
        return result

    def prometheus(self) -> str:
        lines = ["# HELP scrape_attempts_total Total scrape attempts", "# TYPE scrape_attempts_total counter"]
        for c, v in self._attempts.items():
            lines.append(f'scrape_attempts_total{{company="{c}"}} {v}')
        lines.append("# HELP scrape_successes_total Successful scrapes")
        lines.append("# TYPE scrape_successes_total counter")
        for c, v in self._successes.items():
            lines.append(f'scrape_successes_total{{company="{c}"}} {v}')
        lines.append("# HELP scrape_failures_total Failed scrapes")
        lines.append("# TYPE scrape_failures_total counter")
        for c, v in self._failures.items():
            lines.append(f'scrape_failures_total{{company="{c}"}} {v}')
        lines.append("# HELP scrape_jobs_total Jobs found")
        lines.append("# TYPE scrape_jobs_total counter")
        for c, v in self._total_jobs.items():
            lines.append(f'scrape_jobs_total{{company="{c}"}} {v}')
        return "\n".join(lines)


metrics = ScrapeMetrics()