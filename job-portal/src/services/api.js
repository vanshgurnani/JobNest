const BASE = import.meta.env.VITE_API_BASE || '/api';

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { Accept: 'application/json', ...options.headers },
    ...options,
  });

  if (!res.ok) {
    if (res.status === 503) {
      throw new Error('Database is not available. Please run the scraper first.');
    }
    if (res.status === 404) {
      throw new Error('Job not found.');
    }
    const text = await res.text().catch(() => '');
    throw new Error(text || `Request failed (${res.status})`);
  }

  return res.json();
}

export async function fetchJobs({ company, keyword, location, page = 1, limit = 20 } = {}) {
  const params = new URLSearchParams();
  if (company) params.set('company', company);
  if (keyword) params.set('keyword', keyword);
  if (location) params.set('location', location);
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
