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
} from '@mui/material';

import SearchBar from './components/SearchBar.jsx';
import JobCard from './components/JobCard.jsx';

const API_BASE = 'https://job-crawler-nkre.onrender.com';

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
  };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export default function App() {
  const [jobs, setJobs] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | success | retrying | empty
  const [message, setMessage] = useState('');

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

  async function fetchJobsFromBackend({ company, keyword, location, signal }) {
    const qs = buildQuery({ company, keyword, location, page: 1, limit: 20 });
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
    };
  }

  async function discover(companyInput) {
    const company = normalizeCompany(companyInput);
    const keyword = String(filters.keyword || '').trim();
    const location = String(filters.location || '').trim();

    const cacheKey = JSON.stringify({ company, keyword, location });
    const cached = cacheRef.current.get(cacheKey);
    if (cached && Date.now() - cached.at < 1000 * 60 * 10) {
      setJobs(cached.jobs);
      setStatus(cached.status);
      setMessage('');
      return;
    }

    requestIdRef.current += 1;
    const rid = requestIdRef.current;

    const ctrl = new AbortController();

    setStatus('loading');
    setMessage('');
    setJobs([]);

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
          signal: ctrl.signal,
        });

        if (rid !== requestIdRef.current) return;

        const uiJobs = (result.jobs || []).slice(0, 20);
        if (uiJobs.length > 0) {
          cacheRef.current.set(cacheKey, { jobs: uiJobs, status: 'success', at: Date.now() });
          setJobs(uiJobs);
          setStatus('success');
          setMessage('');
          return;
        }
      } catch {
        // continue
      }
    }

    if (rid !== requestIdRef.current) return;

    cacheRef.current.set(cacheKey, { jobs: [], status: 'empty', at: Date.now() });
    setJobs([]);
    setStatus('empty');
    setMessage('No jobs found. Try another company.');

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
    discover(normalizedCompany);
  }

  const showTrending = !normalizedCompany;

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
                    <JobCard job={job} />
                  </Box>
                </Grid>
              ))}
            </Grid>
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
    </Box>
  );
}



