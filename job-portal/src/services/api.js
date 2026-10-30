import logger from '../utils/logger';

const BASE = import.meta.env.VITE_API_BASE || '/api';

async function request(url, options = {}) {
  const started = performance.now();
  logger.info('api', `→ ${options.method || 'GET'} ${url}`);

  let res;
  try {
    res = await fetch(`${BASE}${url}`, {
      headers: { Accept: 'application/json', ...options.headers },
      ...options,
    });
  } catch (e) {
    logger.error('api', `Network error on ${url}: ${e.message}`);
    throw e;
  }

  const elapsed = Math.round(performance.now() - started);

  if (!res.ok) {
    if (res.status === 503) {
      logger.warn('api', `503 on ${url} (${elapsed}ms) — DB unavailable`);
      throw new Error('Database is not available. Please run the scraper first.');
    }
    if (res.status === 404) {
      logger.warn('api', `404 on ${url} (${elapsed}ms) — not found`);
      throw new Error('Job not found.');
    }
    const text = await res.text().catch(() => '');
    logger.error('api', `${res.status} on ${url} (${elapsed}ms): ${text}`);
    throw new Error(text || `Request failed (${res.status})`);
  }

  const data = await res.json();
  logger.info('api', `← ${res.status} ${url} (${elapsed}ms)`);
  return data;
}

export async function fetchJobs({ company, keyword, location, employmentType, experience, page = 1, limit = 20 } = {}) {
  const params = new URLSearchParams();
  if (company) params.set('company', company);
  if (keyword) params.set('keyword', keyword);
  if (location) params.set('location', location);
  if (employmentType) params.set('employment_type', employmentType);
  if (experience) params.set('experience', experience);
  params.set('page', String(page));
  params.set('limit', String(limit));

  const qs = params.toString();
  const data = await request(`/jobs${qs ? `?${qs}` : ''}`);

  return {
    jobs: data.jobs || data.latest_jobs || [],
    total: data.total || 0,
    page: data.page || page,
    limit: data.limit || limit,
  };
}

export async function fetchJobById(id) {
  const data = await request(`/job/${encodeURIComponent(id)}`);
  return data.job || null;
}

export async function fetchHealth() {
  return request('/health');
}

export async function fetchCompanies() {
  const data = await request('/companies');
  const raw = data.companies || data.companies_list || [];
  return raw.map((c) => {
    if (typeof c === 'string') return { name: c, count: null };
    return { name: c.name || c.company, count: c.count ?? null };
  });
}

export async function pushJobsToDb(jobs) {
  if (!Array.isArray(jobs) || jobs.length === 0) {
    logger.warn('api', 'pushJobsToDb called with no jobs');
    return 0;
  }
  logger.info('api', `Pushing ${jobs.length} jobs to database...`);
  const data = await request('/push-to-db', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jobs }),
  });
  logger.info('api', `DB push complete: ${data.saved} saved`);
  return data.saved;
}

export async function triggerScrape({ input, keyword, location, pages = 2, saveToDb = true } = {}) {
  const isUrl = input?.startsWith('http://') || input?.startsWith('https://');
  const payload = {
    keyword,
    location,
    pages,
    save_to_db: saveToDb,
  };
  if (isUrl) {
    payload.url = input;
  } else {
    payload.company = input;
  }

  return request('/scrape', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function triggerScrapeAsync({ input, keyword, location, pages = 2, saveToDb = true } = {}) {
  const isUrl = input?.startsWith('http://') || input?.startsWith('https://');
  const payload = {
    keyword,
    location,
    pages,
    save_to_db: saveToDb,
  };
  if (isUrl) {
    payload.url = input;
  } else {
    payload.company = input;
  }

  return request('/scrape/async', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function getScrapeStatus(taskId) {
  return request(`/scrape/async/${encodeURIComponent(taskId)}`);
}

export async function fetchScraperHealth() {
  return request('/scraper-health');
}

export async function resolveCompany(input) {
  return request('/resolve-company', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input }),
  });
}
