import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import Filters from '../components/Filters';
import JobCard from '../components/JobCard';
import SkeletonCard from '../components/SkeletonCard';
import Pagination from '../components/Pagination';
import EmptyState from '../components/EmptyState';
import ErrorState from '../components/ErrorState';
import { fetchJobs } from '../services/api';

const PAGE_SIZE = 20;

export default function FindJobsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const keywordParam = searchParams.get('keyword') || '';
  const locationParam = searchParams.get('location') || '';
  const companyParam = searchParams.get('company') || '';

  const [keyword, setKeyword] = useState(keywordParam);
  const [filters, setFilters] = useState({ employmentType: '', experience: '' });
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setKeyword(keywordParam);
  }, [keywordParam]);

  const loadJobs = useCallback(
    async (pg = 1) => {
      setLoading(true);
      setError(null);
      try {
        const result = await fetchJobs({
          keyword: keywordParam || undefined,
          location: locationParam || undefined,
          company: companyParam || undefined,
          employmentType: filters.employmentType || undefined,
          experience: filters.experience || undefined,
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
    [keywordParam, locationParam, companyParam, filters.employmentType, filters.experience],
  );

  useEffect(() => {
    loadJobs(1);
  }, [loadJobs]);

  function handleSearch(e) {
    e.preventDefault();
    const params = new URLSearchParams();
    if (keyword.trim()) params.set('keyword', keyword.trim());
    if (locationParam) params.set('location', locationParam);
    if (companyParam) params.set('company', companyParam);
    setSearchParams(params);
  }

  function handleFilterChange(next) {
    setFilters(next);
  }

  function handleClear() {
    setKeyword('');
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
          {companyParam ? (
            <h1 className="mb-2 text-2xl font-bold text-ink sm:text-3xl">{companyParam}</h1>
          ) : (
            <h1 className="mb-2 text-2xl font-bold text-ink sm:text-3xl">Find Jobs</h1>
          )}

          <form onSubmit={handleSearch} className="flex max-w-xl gap-2">
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="Search by job title, skill, or keyword..."
              className="min-w-0 flex-1 rounded-lg border bg-white px-4 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:ring-2 focus:ring-accent-500"
            />
            <button type="submit" className="btn-primary whitespace-nowrap text-sm">
              Search
            </button>
          </form>

          {(keywordParam || locationParam || companyParam) && (
            <button onClick={handleClear} className="mt-3 text-sm font-medium text-accent-600 hover:text-accent-700">
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

            {!loading && !error && jobs.length === 0 && !companyParam && (
              <div className="rounded-lg border bg-white p-8 text-center">
                <h2 className="text-lg font-semibold text-ink">We&apos;re working on it</h2>
                <p className="mt-2 text-sm text-ink-secondary">
                  Job listings are being added. Check back soon or browse from the home page.
                </p>
              </div>
            )}

            {!loading && !error && jobs.length === 0 && companyParam && (
              <EmptyState keyword={keywordParam} onClear={handleClear} />
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