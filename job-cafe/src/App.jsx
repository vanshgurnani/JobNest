import React, { useEffect, useMemo, useState } from 'react';
import SearchBar from './components/SearchBar.jsx';
import JobCard from './components/JobCard.jsx';

const API_BASE = 'https://job-crawler-nkre.onrender.com';


function buildQuery(params) {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    const v = String(value).trim();
    if (!v) continue;
    usp.set(key, v);
  }
  const s = usp.toString();
  return s ? `?${s}` : '';
}

export default function App() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [filters, setFilters] = useState({
    company: '',
    keyword: '',
    location: '',
  });

  const activeQuery = useMemo(() => {
    return buildQuery({
      company: filters.company,
      keyword: filters.keyword,
      location: filters.location,
    });
  }, [filters.company, filters.keyword, filters.location]);

  async function fetchJobs(querySuffix) {
    setLoading(true);
    setError('');

    try {
      const res = await fetch(`${API_BASE}/jobs${querySuffix}`, {
        headers: { 'Accept': 'application/json' },
      });

      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text ? `${res.status} ${text}` : `Request failed: ${res.status}`);
      }

      const data = await res.json();
      // Backend returns: { jobs: [...], latest_jobs: [...], total: ... }
      // Some deployments may return array directly; handle both.
      const incoming = Array.isArray(data) ? data : data?.jobs;
      setJobs(Array.isArray(incoming) ? incoming : []);
    } catch (e) {
      setJobs([]);
      setError(e?.message || 'Failed to fetch jobs');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // Initial load: fetch all jobs.
    fetchJobs('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSearch() {
    // Search by current filters.
    fetchJobs(activeQuery);
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header__inner">
          <h1 className="header__title">Job Cafe</h1>
        </div>
      </header>

      <main className="container">
        <section className="search">
          <SearchBar filters={filters} setFilters={setFilters} onSearch={handleSearch} />
        </section>

        <section className="jobs" aria-live="polite">
          {loading && (
            <div className="state state--loading" role="status" aria-label="Loading">
              <div className="spinner" />
              <div className="state__text">Loading jobs…</div>
            </div>
          )}

          {!loading && error && (
            <div className="state state--error">
              <div className="state__text">{error}</div>
            </div>
          )}

          {!loading && !error && jobs.length === 0 && (
            <div className="state state--empty">
              <div className="state__text">No jobs found</div>
            </div>
          )}

          {!loading && !error && jobs.length > 0 && (
            <div className="grid">
              {jobs.map((job) => (
                <JobCard key={job?.id || job?.url} job={job} />
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

