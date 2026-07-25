import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Container,
  Grid,
  Skeleton,
  Typography,
  Paper,
  Chip,
  CircularProgress,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from '@mui/material';

import SearchBar from './components/SearchBar.jsx';
import JobCard from './components/JobCard.jsx';

const API_BASE = import.meta.env.VITE_API_BASE || '';
const PAGE_SIZE = 20;

const COMPANY_ALIASES = {
  meta: 'facebook',
  facebook: 'facebook',
  tcs: 'tata consultancy services',
  'tata consultancy services': 'tata consultancy services',
  'jp morgan': 'jpmorganchase',
  jpmorganchase: 'jpmorganchase',
};

function normalizeCompany(input) {
  const raw = String(input || '').trim().toLowerCase();
  if (!raw) return '';

  if (COMPANY_ALIASES[raw]) return COMPANY_ALIASES[raw];

  const compact = raw.replace(/\s+/g, ' ');
  return COMPANY_ALIASES[compact] || raw;
}

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

function mapBackendJobToUI(job) {
  return {
    title: job?.title || 'Untitled',
    company: job?.company || '',
    location: job?.location || '',
    apply_url: job?.apply_url || job?.url || '',
    source: job?.source || '',
    date_posted: job?.posted_date || job?.date_posted || '',
    id: job?.id,
    url: job?.url,
    description: job?.description,
    skills: job?.skills || [],
    employment_type: job?.employment_type || '',
    experience: job?.experience || '',
  };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export default function App() {
  const [jobs, setJobs] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | success | retrying | empty
  const [message, setMessage] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [selectedJob, setSelectedJob] = useState(null);

  const [filters, setFilters] = useState({
    company: '',
    keyword: '',
    location: '',
  });

  const normalizedCompany = useMemo(() => normalizeCompany(filters.company), [filters.company]);

  const cacheRef = useRef(new Map());
  const requestIdRef = useRef(0);

  const trending = useMemo(
    () => ['Amazon', 'Meta', 'TCS', 'Wipro', 'JP Morgan', 'Microsoft', 'Google', 'Mastercard'],
    [],
  );

  const suggested = useMemo(() => {
    const tokens = normalizedCompany ? normalizedCompany.split(/\s+/g) : [];
    const lower = normalizedCompany;

    const scored = trending
      .map((c) => {
        const cn = c.toLowerCase();
        let s = 0;
        for (const t of tokens) if (t && cn.includes(t)) s += 2;
        if (lower && (cn.includes(lower) || lower.includes(cn))) s += 3;
        return { c, s };
      })
      .sort((a, b) => b.s - a.s)
      .filter((x) => x.s > 0)
      .slice(0, 5)
      .map((x) => x.c);

    return scored;
  }, [normalizedCompany, trending]);

  async function fetchJobsFromBackend({ company, keyword, location, page: pageNumber, signal }) {
    const qs = buildQuery({ company, keyword, location, page: pageNumber, limit: PAGE_SIZE });
    const url = `${API_BASE}/jobs${qs}`;

    const res = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(text ? `${res.status} ${text}` : `Request failed: ${res.status}`);
    }

    const data = await res.json();
    const incoming = Array.isArray(data) ? data : data?.jobs;
    const normalized = (Array.isArray(incoming) ? incoming : []).map(mapBackendJobToUI);

    return {
      jobs: normalized,
      total: Number(data?.total || normalized.length),
      page: Number(data?.page || pageNumber),
    };
  }

  async function discover(companyInput, pageNumber = 1, { append = false } = {}) {
    const company = normalizeCompany(companyInput);
    const keyword = String(filters.keyword || '').trim();
    const location = String(filters.location || '').trim();

    const cacheKey = JSON.stringify({ company, keyword, location, page: pageNumber });
    const cached = cacheRef.current.get(cacheKey);
    if (cached && Date.now() - cached.at < 1000 * 60 * 10) {
      setJobs((prev) => (append ? [...prev, ...cached.jobs] : cached.jobs));
      setStatus(cached.status);
      setPage(pageNumber);
      setTotal(cached.total || cached.jobs.length);
      setIsLoadingMore(false);
      setMessage('');
      return;
    }

    requestIdRef.current += 1;
    const rid = requestIdRef.current;

    const ctrl = new AbortController();

    if (append) {
      setIsLoadingMore(true);
    } else {
      setStatus('loading');
      setJobs([]);
      setPage(1);
      setTotal(0);
    }
    setMessage('');

    const attempts = [];
    const aliasAttempt1 = company;
    const aliasAttempt2 = COMPANY_ALIASES[company] || company;

    attempts.push({ company: aliasAttempt1, keyword, location, status: 'loading' });
    if (aliasAttempt2 !== aliasAttempt1) {
      attempts.push({ company: aliasAttempt2, keyword, location, status: 'retrying' });
    }
    attempts.push({ company: aliasAttempt2, keyword: '', location: '', status: 'retrying' });

    for (let i = 0; i < attempts.length; i++) {
      const a = attempts[i];
      if (rid !== requestIdRef.current) return;

      if (i === 1) {
        setStatus('retrying');
        setMessage('No jobs found. Trying more sources…');
      }

      try {
        await sleep(120);
        const result = await fetchJobsFromBackend({
          company: a.company,
          keyword: a.keyword,
          location: a.location,
          page: pageNumber,
          signal: ctrl.signal,
        });

        if (rid !== requestIdRef.current) return;

        const uiJobs = (result.jobs || []).slice(0, PAGE_SIZE);
        if (uiJobs.length > 0) {
          cacheRef.current.set(cacheKey, {
            jobs: uiJobs,
            status: 'success',
            total: result.total,
            at: Date.now(),
          });
          setJobs((prev) => (append ? [...prev, ...uiJobs] : uiJobs));
          setPage(pageNumber);
          setTotal(result.total);
          setStatus('success');
          setMessage('');
          setIsLoadingMore(false);
          return;
        }
      } catch {
        // continue
      }
    }

    if (rid !== requestIdRef.current) return;

    cacheRef.current.set(cacheKey, { jobs: [], status: append ? 'success' : 'empty', at: Date.now() });
    if (append) {
      setStatus('success');
      setMessage('');
    } else {
      setJobs([]);
      setStatus('empty');
      setMessage('No jobs found. Try another company.');
    }
    setIsLoadingMore(false);

  }

  useEffect(() => {
    const company = normalizedCompany;

    if (!company) {
      setStatus('success');
      setJobs([]);
      setMessage('');
      return;
    }

    const t = setTimeout(() => {
      discover(company);
    }, 450);

    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [normalizedCompany, filters.keyword, filters.location]);

  function handleSearch() {
    if (!normalizedCompany) return;
    discover(normalizedCompany, 1);
  }

  function handleLoadMore() {
    if (!normalizedCompany || isLoadingMore) return;
    discover(normalizedCompany, page + 1, { append: true });
  }

  function handlePageChange(nextPage) {
    if (!normalizedCompany || isLoadingMore || nextPage < 1 || nextPage > totalPages) return;
    window.scrollTo({ top: 120, behavior: 'smooth' });
    discover(normalizedCompany, nextPage);
  }

  const showTrending = !normalizedCompany;
  const canLoadMore = jobs.length > 0 && jobs.length < total;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const canPagePrevious = page > 1;
  const canPageNext = page < totalPages;

  // Generate visible page numbers for pagination toolbar
  const visiblePages = useMemo(() => {
    const pages = [];
    const maxVisible = 5;
    let start = Math.max(1, page - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);

    if (end - start + 1 < maxVisible) {
      start = Math.max(1, end - maxVisible + 1);
    }

    for (let p = start; p <= end; p++) {
      pages.push(p);
    }
    return pages;
  }, [page, totalPages]);

  const startCount = (page - 1) * PAGE_SIZE + 1;
  const endCount = Math.min(page * PAGE_SIZE, total);

  return (
    <Box sx={{ minHeight: '100vh' }}>
      <Box
        component="header"
        sx={{
          py: 3,
          borderBottom: '1px solid rgba(255,255,255,0.10)',
          backgroundColor: 'rgba(15, 23, 42, 0.55)',
          backdropFilter: 'blur(10px)',
        }}
      >
        <Container maxWidth="lg">
          <Typography
            variant="h5"
            sx={{ fontWeight: 800, letterSpacing: '0.2px', color: 'text.primary' }}
          >
            Job Cafe
          </Typography>
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ mt: 6, pb: 8 }}>
        <Box sx={{ mb: 3 }}>
          <SearchBar filters={filters} setFilters={setFilters} onSearch={handleSearch} />
        </Box>

        <Box aria-live="polite">
          {status === 'loading' && (
            <Grid container spacing={3} role="status" aria-label="Loading">
              {Array.from({ length: 8 }).map((_, idx) => (
                <Grid item xs={12} md={6} key={idx}>
                  <Paper
                    elevation={0}
                    sx={{
                      borderRadius: '16px',
                      border: '1px solid rgba(255,255,255,0.10)',
                      backgroundColor: '#111827',
                      p: 2.2,
                      overflow: 'hidden',
                    }}
                  >
                    <Skeleton variant="text" width="70%" height={26} />
                    <Box sx={{ mt: 1.5, display: 'flex', gap: 1 }}>
                      <Skeleton variant="circular" width={28} height={28} />
                      <Skeleton variant="rectangular" width={120} height={28} sx={{ borderRadius: 999 }} />
                    </Box>
                    <Skeleton variant="text" sx={{ mt: 1.6 }} height={18} />
                    <Skeleton variant="text" height={18} />
                    <Skeleton variant="rounded" width={110} height={40} sx={{ mt: 2.2 }} />
                  </Paper>
                </Grid>
              ))}
            </Grid>
          )}

          {(status === 'retrying' || (status === 'empty' && message)) && status !== 'loading' && (
            <Box
              sx={{
                mt: 2,
                p: 3,
                borderRadius: '16px',
                border: '1px solid rgba(255,255,255,0.10)',
                backgroundColor: 'rgba(255,255,255,0.03)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
              }}
            >
              <CircularProgress size={26} sx={{ color: 'primary.main' }} />
              <Typography sx={{ color: 'text.secondary', fontWeight: 600 }}>
                {message || 'No jobs found, trying more sources…'}
              </Typography>
            </Box>
          )}

          {showTrending && (
            <Box sx={{ mt: 2 }}>
              <Typography sx={{ mb: 1.2, fontSize: 13, color: 'text.secondary', fontWeight: 700 }}>
                Trending Companies
              </Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1.2 }}>
                {trending.map((c) => (
                  <Chip
                    key={c}
                    label={c}
                    clickable
                    onClick={() => setFilters((prev) => ({ ...prev, company: c, keyword: '', location: '' }))}
                    sx={{
                      borderRadius: 999,
                      border: '1px solid rgba(59,130,246,0.35)',
                      backgroundColor: 'rgba(59,130,246,0.08)',
                      '&:hover': { filter: 'brightness(1.05)' },
                      fontWeight: 700,
                      color: 'text.primary',
                    }}
                  />
                ))}
              </Box>
            </Box>
          )}

          {status === 'success' && jobs.length === 0 && !showTrending && (
            <Box
              sx={{
                mt: 2,
                p: 4,
                textAlign: 'center',
                borderRadius: '16px',
                border: '1px dashed rgba(255,255,255,0.14)',
                backgroundColor: 'rgba(255,255,255,0.02)',
              }}
            >
              <Typography sx={{ fontWeight: 900, letterSpacing: '0.2px' }}>
                No jobs found. Try another company.
              </Typography>
              {suggested.length > 0 && (
                <Box sx={{ mt: 2, display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 1.2 }}>
                  {suggested.map((c) => (
                    <Chip
                      key={c}
                      label={c}
                      clickable
                      onClick={() => setFilters((prev) => ({ ...prev, company: c }))}
                      sx={{
                        borderRadius: 999,
                        border: '1px solid rgba(255,255,255,0.16)',
                        backgroundColor: 'rgba(255,255,255,0.03)',
                        '&:hover': { borderColor: 'rgba(59,130,246,0.45)' },
                        color: 'text.secondary',
                        fontWeight: 800,
                      }}
                    />
                  ))}
                </Box>
              )}
            </Box>
          )}

          {(status === 'success' || status === 'retrying') && jobs.length > 0 && (
            <Grid container spacing={3} sx={{ mt: 1 }}>
              {jobs.map((job, idx) => (
                <Grid item xs={12} md={6} key={job?.id || job?.url || job?.apply_url}>
                  <Box sx={{ animation: `fadeInUp 320ms ease ${idx * 60}ms both` }}>
                    <JobCard job={job} onView={() => setSelectedJob(job)} />
                  </Box>
                </Grid>
              ))}
            </Grid>
          )}

          {status === 'success' && jobs.length > 0 && (
            <Box
              sx={{
                mt: 5,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 2,
              }}
            >
              {total > 0 && (
                <Typography sx={{ color: 'text.secondary', fontSize: 14, fontWeight: 700 }}>
                  Showing {startCount}–{endCount} of {total} jobs
                </Typography>
              )}

              <Box
                sx={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 1,
                  p: 1,
                  borderRadius: 999,
                  backgroundColor: 'rgba(17, 24, 39, 0.7)',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  backdropFilter: 'blur(8px)',
                }}
              >
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => handlePageChange(page - 1)}
                  disabled={!canPagePrevious || isLoadingMore}
                  sx={{ borderRadius: 999, px: 2, py: 0.8, fontWeight: 800, minWidth: 90 }}
                >
                  Previous
                </Button>

                {visiblePages[0] > 1 && (
                  <>
                    <Button
                      size="small"
                      variant="text"
                      onClick={() => handlePageChange(1)}
                      sx={{ borderRadius: 999, minWidth: 36, height: 36, fontWeight: 800, color: 'text.secondary' }}
                    >
                      1
                    </Button>
                    {visiblePages[0] > 2 && (
                      <Typography sx={{ px: 0.5, color: 'text.secondary', fontWeight: 800 }}>...</Typography>
                    )}
                  </>
                )}

                {visiblePages.map((p) => (
                  <Button
                    key={p}
                    size="small"
                    variant={p === page ? 'contained' : 'text'}
                    onClick={() => handlePageChange(p)}
                    disabled={isLoadingMore}
                    sx={{
                      borderRadius: 999,
                      minWidth: 36,
                      height: 36,
                      fontWeight: 800,
                      backgroundColor: p === page ? 'primary.main' : 'transparent',
                      color: p === page ? '#fff' : 'text.secondary',
                      '&:hover': {
                        backgroundColor: p === page ? 'primary.dark' : 'rgba(255,255,255,0.08)',
                      },
                    }}
                  >
                    {p}
                  </Button>
                ))}

                {visiblePages[visiblePages.length - 1] < totalPages && (
                  <>
                    {visiblePages[visiblePages.length - 1] < totalPages - 1 && (
                      <Typography sx={{ px: 0.5, color: 'text.secondary', fontWeight: 800 }}>...</Typography>
                    )}
                    <Button
                      size="small"
                      variant="text"
                      onClick={() => handlePageChange(totalPages)}
                      sx={{ borderRadius: 999, minWidth: 36, height: 36, fontWeight: 800, color: 'text.secondary' }}
                    >
                      {totalPages}
                    </Button>
                  </>
                )}

                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => handlePageChange(page + 1)}
                  disabled={!canPageNext || isLoadingMore}
                  sx={{ borderRadius: 999, px: 2, py: 0.8, fontWeight: 800, minWidth: 90 }}
                >
                  {isLoadingMore ? 'Loading...' : 'Next'}
                </Button>
              </Box>
            </Box>
          )}

          {status === 'empty' && jobs.length === 0 && !showTrending && (
            <Box
              sx={{
                mt: 2,
                p: 4,
                textAlign: 'center',
                borderRadius: '16px',
                border: '1px dashed rgba(255,255,255,0.14)',
                backgroundColor: 'rgba(255,255,255,0.02)',
              }}
            >
              <Typography sx={{ fontWeight: 900, letterSpacing: '0.2px' }}>
                {message || 'No jobs found. Try another company.'}
              </Typography>
            </Box>
          )}
        </Box>
      </Container>

      <Dialog
        open={Boolean(selectedJob)}
        onClose={() => setSelectedJob(null)}
        fullWidth
        maxWidth="md"
        PaperProps={{
          sx: {
            bgcolor: '#111827',
            color: 'text.primary',
            border: '1px solid rgba(255,255,255,0.12)',
          },
        }}
      >
        <DialogTitle sx={{ fontWeight: 900 }}>{selectedJob?.title || 'Job details'}</DialogTitle>
        <DialogContent dividers sx={{ borderColor: 'rgba(255,255,255,0.10)' }}>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
            {[selectedJob?.company, selectedJob?.location, selectedJob?.employment_type, selectedJob?.experience]
              .filter(Boolean)
              .map((label) => (
                <Chip key={label} size="small" label={label} sx={{ color: 'text.primary' }} />
              ))}
          </Box>
          {selectedJob?.skills?.length > 0 && (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
              {selectedJob.skills.slice(0, 12).map((skill) => (
                <Chip key={skill} size="small" label={skill} variant="outlined" />
              ))}
            </Box>
          )}
          <Typography sx={{ color: 'text.secondary', whiteSpace: 'pre-line', lineHeight: 1.7 }}>
            {selectedJob?.description || 'No description was available from the source.'}
          </Typography>
        </DialogContent>
        <DialogActions sx={{ p: 2 }}>
          <Button onClick={() => setSelectedJob(null)} sx={{ fontWeight: 800 }}>
            Close
          </Button>
          <Button
            component="a"
            href={selectedJob?.apply_url || selectedJob?.url || '#'}
            target="_blank"
            rel="noreferrer"
            variant="contained"
            disableElevation
            sx={{ borderRadius: 999, fontWeight: 800 }}
          >
            Apply
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
