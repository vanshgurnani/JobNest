import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchCompanies } from '../services/api';
import ErrorState from '../components/ErrorState';

function initials(name) {
  return (name || '?')
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

export default function CompaniesPage() {
  const navigate = useNavigate();
  const [companies, setCompanies] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchCompanies()
      .then(setCompanies)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter((c) => c.name.toLowerCase().includes(q));
  }, [companies, query]);

  const totalJobs = companies.reduce((sum, c) => sum + (c.count || 0), 0);

  function handleCompanyClick(name) {
    navigate(`/jobs?company=${encodeURIComponent(name)}`);
  }

  return (
    <main>
      <div className="border-b bg-white">
        <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
          <h1 className="mb-2 text-2xl font-bold text-ink sm:text-3xl">Companies</h1>
          <p className="text-sm text-ink-secondary sm:text-base">
            Browse open roles from {companies.length} companies offering jobs.
          </p>

          <div className="mt-6 max-w-md">
            <label className="sr-only" htmlFor="company-search">Search companies</label>
            <input
              id="company-search"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search companies..."
              className="input-field"
            />
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        {loading && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="skeleton h-28 rounded-xl" />
            ))}
          </div>
        )}

        {error && !loading && <ErrorState message={error} onRetry={() => window.location.reload()} />}

        {!loading && !error && filtered.length === 0 && (
          <div className="rounded-lg border bg-white p-10 text-center">
            <h2 className="text-lg font-semibold text-ink">No companies found</h2>
            <p className="mt-2 text-sm text-ink-secondary">
              {query.trim()
                ? `No companies match "${query.trim()}".`
                : 'Company listings are being added. Check back soon.'}
            </p>
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <>
            <p className="mb-4 text-sm text-ink-muted">
              {filtered.length} compan{filtered.length === 1 ? 'y' : 'ies'}
              {totalJobs > 0 && ` · ${totalJobs.toLocaleString()} jobs`}
            </p>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((company) => (
                <button
                  key={company.name}
                  onClick={() => handleCompanyClick(company.name)}
                  className="card group flex items-center gap-4 p-5 text-left transition-all hover:-translate-y-0.5 hover:shadow-card-hover active:scale-[0.99]"
                >
                  <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-xl bg-accent-50 text-sm font-bold text-accent-600 transition-colors group-hover:bg-accent-100">
                    {initials(company.name)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-base font-semibold text-ink group-hover:text-accent-600">
                      {company.name}
                    </h2>
                    {company.count != null && (
                      <p className="mt-0.5 text-sm text-ink-muted">
                        {company.count} open job{company.count === 1 ? '' : 's'}
                      </p>
                    )}
                  </div>
                  <svg className="h-4 w-4 flex-shrink-0 text-ink-muted transition-transform group-hover:translate-x-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  );
}
