import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchJobs } from '../services/api';

const CACHE_TTL = 10 * 60 * 1000;
const MAX_CACHE_ENTRIES = 50;

function lruEvict(map, max) {
  if (map.size <= max) return;
  const first = map.keys().next().value;
  if (first) map.delete(first);
}

export function useJobs({ company, keyword, location, employmentType, experience } = {}) {
  const [data, setData] = useState({ jobs: [], total: 0, page: 1 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const cacheRef = useRef(new Map());
  const requestIdRef = useRef(0);

  const load = useCallback(
    async (page = 1, append = false) => {
      const cacheKey = JSON.stringify({ company, keyword, location, employmentType, experience, page });
      const cached = cacheRef.current.get(cacheKey);
      if (cached && Date.now() - cached.at < CACHE_TTL) {
        setData((prev) => ({
          jobs: append ? [...prev.jobs, ...cached.jobs] : cached.jobs,
          total: cached.total,
          page,
        }));
        setLoading(false);
        setError(null);
        return;
      }

      requestIdRef.current += 1;
      const rid = requestIdRef.current;

      setLoading(true);
      setError(null);
      if (!append) {
        setData({ jobs: [], total: 0, page: 1 });
      }

      try {
        const result = await fetchJobs({ company, keyword, location, employmentType, experience, page });
        if (rid !== requestIdRef.current) return;

        cacheRef.current.set(cacheKey, { jobs: result.jobs, total: result.total, at: Date.now() });
        lruEvict(cacheRef.current, MAX_CACHE_ENTRIES);

        setData((prev) => ({
          jobs: append ? [...prev.jobs, ...result.jobs] : result.jobs,
          total: result.total,
          page,
        }));
      } catch (err) {
        if (rid !== requestIdRef.current) return;
        setError(err.message || 'Failed to load jobs');
      } finally {
        if (rid === requestIdRef.current) {
          setLoading(false);
        }
      }
    },
    [company, keyword, location, employmentType, experience],
  );

  useEffect(() => {
    load(1);
  }, [load]);

  return { ...data, loading, error, load };
}
