from __future__ import annotations
import asyncio
import logging
from typing import Any
from urllib.parse import quote, urljoin
from app.crawler.base import normalize_job_payload, request_json_with_retries

logger = logging.getLogger(__name__)


async def fetch_amazon_jobs(keyword: str = 'Software', location: str = 'Bangalore', max_pages: int = 3) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    base_url = 'https://www.amazon.jobs/en/search.json'

    for page in range(1, max_pages + 1):
        try:
            search_url = f"{base_url}?base_query={quote(keyword)}&loc_query={quote(location)}&page={page}&result_limit=20"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json',
            }
            data = await request_json_with_retries(search_url, headers=headers, timeout=25.0)
            if not data or 'jobs' not in data:
                break
            
            raw_jobs = data['jobs']
            if not raw_jobs:
                break
                
            for raw_job in raw_jobs:
                job_id = raw_job.get('id') or ''
                title = raw_job.get('title') or ''
                
                loc_parts = []
                for key in ('city', 'state', 'country_code'):
                    val = raw_job.get(key)
                    if val:
                        loc_parts.append(val)
                job_loc = ", ".join(loc_parts) if loc_parts else raw_job.get('location', location)
                
                desc = raw_job.get('description') or ''
                basic = raw_job.get('basic_qualifications') or ''
                pref = raw_job.get('preferred_qualifications') or ''
                
                full_desc = desc
                if basic:
                    full_desc += f"\n\nBasic Qualifications:\n{basic}"
                if pref:
                    full_desc += f"\n\nPreferred Qualifications:\n{pref}"
                
                apply_url = urljoin('https://www.amazon.jobs', raw_job.get('job_path') or '')
                category = raw_job.get('job_category') or ''
                
                normalized = normalize_job_payload(
                    {
                        'job_id': job_id,
                        'title': title,
                        'location': job_loc,
                        'description': full_desc,
                        'apply_url': apply_url,
                        'employment_type': raw_job.get('job_schedule_type') or 'Full Time',
                        'experience': '',
                        'skills': [],
                        'team': category,
                    },
                    'Amazon',
                    'amazon',
                )
                if normalized.get('title'):
                    jobs.append(normalized)
            
            if len(raw_jobs) < 20:
                break
                
            await asyncio.sleep(0.2)
        except Exception as exc:
            logger.warning('Amazon crawler failed: %s', exc)
            break

    return jobs
