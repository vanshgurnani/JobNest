const BASE = import.meta.env.VITE_API_BASE || '/api';

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: 'application/json', ...options.headers },
    ...options,
  });
  const contentType = response.headers.get('content-type') || '';
  const body = contentType.includes('application/json')
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const message = typeof body === 'object' ? body.detail || body.error : body;
    throw new Error(message || `Request failed (${response.status})`);
  }
  return body;
}

export async function discoverPortal(input) {
  return request('/scraper/discover', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      company: input.company || undefined,
      domain: input.domain || undefined,
      company_url: input.careerUrl || undefined,
    }),
  });
}

export async function startRun(config) {
  const response = await request('/scrape/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      companies: config.companies,
      company_url: config.companyUrl,
      save_to_db: config.mode === 'db',
      pages: Number(config.pages),
      page_size: Number(config.pageSize),
      delay_seconds: Number(config.delaySeconds),
      concurrency: Number(config.concurrency),
      keyword: config.keyword,
      location: config.location,
    }),
  });
  return response.task_id;
}

export function getRun(id) {
  return request(`/scrape/status/${encodeURIComponent(id)}`);
}

export async function getRuns() {
  const data = await request('/scrape/status');
  return data.runs || [];
}

export async function stopRun(id) {
  return request(`/scrape/stop/${encodeURIComponent(id)}`, { method: 'POST' });
}

export async function getMetrics() {
  return request('/metrics');
}

export async function getCompanies() {
  const data = await request('/companies');
  return (data.companies || []).map((company) => (
      typeof company === 'string'
      ? { name: company, count: null, careers_url: '' }
      : { ...company, careers_url: company.careers_url || company.career_url || company.career_page_url || '' }
  ));
}

export async function getJobs({ company = '', keyword = '', location = '', page = 1, limit = 25 } = {}) {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (company) params.set('company', company);
  if (keyword) params.set('keyword', keyword);
  if (location) params.set('location', location);
  return request(`/jobs?${params.toString()}`);
}
