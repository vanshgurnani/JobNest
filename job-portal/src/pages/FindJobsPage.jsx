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

  const keyword = searchParams.get('keyword') || '';
  const location = searchParams.get('location') || '';
  const company = searchParams.get('company') || '';

  const [filters, setFilters] = useState({ type: '', experience: '', salary: '' });
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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
          <h1 className="text-2xl font-bold text-ink sm:text-3xl">Find Jobs</h1>
          <p className="mt-1 text-sm text-ink-secondary">
            {keyword || location || company
              ? `Results for ${[company, keyword, location].filter(Boolean).join(' · ')}`
              : 'Browse all available positions'}
          </p>

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
