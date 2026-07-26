import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import Filters from '../components/Filters';
import JobCard from '../components/JobCard';
import SkeletonCard from '../components/SkeletonCard';
import Pagination from '../components/Pagination';
import EmptyState from '../components/EmptyState';
import ErrorState from '../components/ErrorState';
import { fetchJobs, fetchCompanies } from '../services/api';

const PAGE_SIZE = 20;

export default function FindJobsPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const keyword = searchParams.get('keyword') || '';
  const location = searchParams.get('location') || '';
  const company = searchParams.get('company') || '';

  const [filters, setFilters] = useState({ type: '', experience: '', salary: '' });
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [allCompanies, setAllCompanies] = useState([]);
  const [companyInput, setCompanyInput] = useState(company);
  const [showDropdown, setShowDropdown] = useState(false);
  const [filteredCompanies, setFilteredCompanies] = useState([]);
  const companyRef = useRef(null);

  useEffect(() => {
    fetchCompanies().then(setAllCompanies).catch(() => {});
  }, []);

  useEffect(() => {
    setCompanyInput(company);
  }, [company]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (companyRef.current && !companyRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  function handleCompanyInputChange(value) {
    setCompanyInput(value);
    setShowDropdown(true);
    const search = value.toLowerCase();
    setFilteredCompanies(
      search
        ? allCompanies.filter((c) => c.toLowerCase().includes(search))
        : allCompanies,
    );
  }

  function handleCompanySelect(selected) {
    setCompanyInput(selected);
    setShowDropdown(false);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (selected) next.set('company', selected);
      else next.delete('company');
      return next;
    });
  }

  const loadJobs = useCallback(
    async (pg = 1) => {
      setLoading(true);
      setError(null);
      try {
        const result = await fetchJobs({
          keyword: keyword || undefined,
          location: location || undefined,
          company: company || undefined,
          page: pg,
          limit: PAGE_SIZE,
        });
        setJobs(result.jobs);
        setTotal(result.total);
        setPage(pg);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    },
    [keyword, location, company],
  );

  useEffect(() => {
    loadJobs(1);
  }, [loadJobs]);

  function handleFilterChange(next) {
    setFilters(next);
  }

  function handleClearSearch() {
    setSearchParams({});
  }

  function handlePageChange(pg) {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    loadJobs(pg);
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <main>
      <div className="border-b bg-white">
        <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-2xl font-bold text-ink sm:text-3xl">Find Jobs</h1>
              <p className="mt-1 text-sm text-ink-secondary">
                {keyword || location || company
                  ? `Results for ${[company, keyword, location].filter(Boolean).join(' · ')}`
                  : 'Browse all available positions'}
              </p>
            </div>

            <div className="relative w-full sm:w-64" ref={companyRef}>
              <label className="sr-only" htmlFor="company-filter">Company</label>
              <input
                id="company-filter"
                type="text"
                value={companyInput}
                onChange={(e) => handleCompanyInputChange(e.target.value)}
                onFocus={() => { setShowDropdown(true); setFilteredCompanies(allCompanies); }}
                placeholder="Search companies..."
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:ring-2 focus:ring-accent-500"
              />
              {companyInput && (
                <button
                  onClick={() => handleCompanySelect('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink"
                >
                  &times;
                </button>
              )}
              {showDropdown && (
                <div className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border bg-white shadow-lg">
                  {filteredCompanies.length === 0 ? (
                    <div className="px-3 py-2 text-sm text-ink-muted">No companies found</div>
                  ) : (
                    filteredCompanies.map((c) => (
                      <button
                        key={c}
                        onClick={() => handleCompanySelect(c)}
                        className={`w-full px-3 py-2 text-left text-sm transition-colors hover:bg-accent-50 ${
                          c === company ? 'font-semibold text-accent-600' : 'text-ink'
                        }`}
                      >
                        {c}
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>

          {(keyword || location || company) && (
            <button
              onClick={handleClearSearch}
              className="mt-3 text-sm font-medium text-accent-600 hover:text-accent-700"
            >
              Clear all filters
            </button>
          )}
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="flex gap-8">
          <aside className="hidden w-56 flex-shrink-0 lg:block">
            <div className="sticky top-24">
              <Filters filters={filters} onChange={handleFilterChange} />
            </div>
          </aside>

          <div className="min-w-0 flex-1">
            {total > 0 && !loading && (
              <p className="mb-4 text-sm text-ink-muted">
                {total} job{total !== 1 ? 's' : ''} found
              </p>
            )}

            {loading && (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <SkeletonCard key={i} />
                ))}
              </div>
            )}

            {error && !loading && (
              <ErrorState message={error} onRetry={() => loadJobs(page)} />
            )}

            {!loading && !error && jobs.length === 0 && (
              <EmptyState
                keyword={keyword}
                location={location}
                onClear={handleClearSearch}
              />
            )}

            {!loading && jobs.length > 0 && (
              <div className="space-y-3">
                {jobs.map((job) => (
                  <JobCard key={job.id || job.job_id} job={job} />
                ))}
              </div>
            )}

            {!loading && jobs.length > 0 && (
              <Pagination
                page={page}
                totalPages={totalPages}
                onPageChange={handlePageChange}
              />
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
