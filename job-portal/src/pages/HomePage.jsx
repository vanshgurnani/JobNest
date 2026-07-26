import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchCompanies } from '../services/api';

function useSlideIn(threshold = 0.1) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisible(true); obs.disconnect(); } },
      { threshold },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold]);

  return [ref, visible];
}

function AnimatedSection({ children, className = '', delay = 0 }) {
  const [ref, visible] = useSlideIn();
  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(24px)',
        transition: `opacity 0.6s ease-out ${delay}s, transform 0.6s ease-out ${delay}s`,
      }}
    >
      {children}
    </div>
  );
}

function FloatingOrb({ className, animClass = 'animate-float-slow', style }) {
  return (
    <div
      className={`hero-glow ${animClass} ${className}`}
      style={style}
      aria-hidden="true"
    />
  );
}

export default function HomePage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [location, setLocation] = useState('');
  const [company, setCompany] = useState('');
  const [companies, setCompanies] = useState([]);

  useEffect(() => {
    fetchCompanies().then(setCompanies).catch(() => {});
  }, []);

  function handleSearch(e) {
    e.preventDefault();
    const params = new URLSearchParams();
    if (keyword.trim()) params.set('keyword', keyword.trim());
    if (location.trim()) params.set('location', location.trim());
    if (company.trim()) params.set('company', company.trim());
    navigate(`/jobs${params.toString() ? `?${params.toString()}` : ''}`);
  }

  function handleCompanyClick(name) {
    navigate(`/jobs?company=${encodeURIComponent(name)}`);
  }

  return (
    <main className="min-h-screen">
      <section className="relative overflow-hidden bg-surface-secondary bg-gradient-mesh">
        <div className="absolute inset-0 bg-grid-pattern" />

        <FloatingOrb
          className="-left-32 -top-32 h-96 w-96"
          animClass="animate-float-slow"
          style={{ background: 'radial-gradient(circle, rgba(59,130,246,0.25) 0%, transparent 70%)' }}
        />
        <FloatingOrb
          className="-bottom-40 -right-32 h-[30rem] w-[30rem]"
          animClass="animate-float"
          style={{ background: 'radial-gradient(circle, rgba(37,99,235,0.2) 0%, transparent 70%)' }}
        />
        <FloatingOrb
          className="left-1/2 top-1/3 h-64 w-64"
          animClass="animate-float-slow"
          style={{ background: 'radial-gradient(circle, rgba(219,234,254,0.3) 0%, transparent 60%)' }}
        />

        <div className="relative mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28 lg:py-36">
          <div className="mx-auto max-w-2xl text-center">
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-accent-200/60 bg-accent-50/80 px-4 py-1.5 text-xs font-medium text-accent-700 shadow-sm backdrop-blur-sm"
              style={{ animation: 'fade-in-down 0.5s ease-out both' }}
            >
              <span className="flex h-1.5 w-1.5 rounded-full bg-accent-500 animate-pulse-soft" />
              Job listing portal
            </span>

            <h1
              className="mt-6 text-4xl font-bold tracking-tight text-ink sm:text-5xl lg:text-6xl"
              style={{ animation: 'fade-in-up 0.6s ease-out 0.15s both' }}
            >
              Find your next{' '}
              <span className="bg-gradient-to-r from-accent-600 to-blue-500 bg-clip-text text-transparent">
                opportunity
              </span>
            </h1>

            <p
              className="mx-auto mt-4 max-w-lg text-base leading-relaxed text-ink-secondary sm:text-lg"
              style={{ animation: 'fade-in-up 0.6s ease-out 0.3s both' }}
            >
              Search thousands of jobs from the world&apos;s best companies.
            </p>
          </div>

          <div
            style={{ animation: 'scale-in 0.5s ease-out 0.45s both' }}
            className="relative"
          >
            <form
              onSubmit={handleSearch}
              className="glass-card mx-auto mt-10 max-w-3xl rounded-2xl p-1.5 sm:flex sm:items-center sm:gap-0"
            >
              <div className="flex-1 border-b sm:border-b-0 sm:border-r sm:border-white/20">
                <label className="sr-only" htmlFor="hero-keyword">
                  Job title or keyword
                </label>
                <input
                  id="hero-keyword"
                  type="text"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="Job title or keyword"
                  className="w-full rounded-xl border-0 bg-transparent px-4 py-3.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none sm:rounded-r-none"
                />
              </div>
              <div className="flex-1 border-b sm:border-b-0 sm:border-r sm:border-white/20">
                <label className="sr-only" htmlFor="hero-location">
                  Location
                </label>
                <input
                  id="hero-location"
                  type="text"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Location"
                  className="w-full rounded-xl border-0 bg-transparent px-4 py-3.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none sm:rounded-none"
                />
              </div>
              <div className="flex-1">
                <label className="sr-only" htmlFor="hero-company">
                  Company
                </label>
                <input
                  id="hero-company"
                  type="text"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="Company"
                  className="w-full rounded-xl border-0 bg-transparent px-4 py-3.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none"
                />
              </div>
              <div className="p-1 sm:flex-shrink-0">
                <button type="submit" className="btn-primary w-full sm:w-auto">
                  Search
                </button>
              </div>
            </form>
          </div>

          <AnimatedSection delay={0.6} className="mx-auto mt-16 max-w-3xl">
            <p className="mb-4 text-center text-xs font-semibold uppercase tracking-widest text-ink-muted">
              Popular companies
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {companies.map((name, i) => (
                <button
                  key={name}
                  onClick={() => handleCompanyClick(name)}
                  className="rounded-full border border-border bg-white/70 px-4 py-1.5 text-sm font-medium text-ink-secondary shadow-sm backdrop-blur-sm transition-all hover:border-accent-300 hover:bg-accent-50/80 hover:text-accent-600 hover:shadow-md active:scale-95"
                  style={{
                    animation: `fade-in-up 0.4s ease-out ${0.7 + i * 0.05}s both`,
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
          </AnimatedSection>
        </div>

        <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-accent-200/50 to-transparent" />
      </section>

      <AnimatedSection delay={0.2}>
        <section className="relative bg-white">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_50%_80%_at_50%_-20%,rgba(59,130,246,0.04)_0%,transparent_70%)]" />
          <div className="relative mx-auto max-w-6xl px-4 py-24 text-center sm:px-6">
            <div className="mx-auto max-w-lg">
              <h2 className="text-2xl font-bold text-ink sm:text-3xl">
                Ready to find your next role?
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
                Start browsing thousands of jobs from top companies right now.
              </p>
              <button
                onClick={() => navigate('/jobs')}
                className="btn-primary mt-8 transition-all hover:scale-105 hover:shadow-lg active:scale-95"
              >
                Browse all jobs
              </button>
            </div>
          </div>
        </section>
      </AnimatedSection>
    </main>
  );
}