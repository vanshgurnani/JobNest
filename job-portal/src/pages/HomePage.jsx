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

export default function HomePage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [location, setLocation] = useState('');
  const [company, setCompany] = useState('');
  const [companies, setCompanies] = useState([]);
  const [showCompanyDropdown, setShowCompanyDropdown] = useState(false);
  const [companyFilter, setCompanyFilter] = useState('');
  const companyRef = useRef(null);

  useEffect(() => {
    fetchCompanies().then(setCompanies).catch(() => {});
  }, []);

  useEffect(() => {
    function handleClickOutside(e) {
      if (companyRef.current && !companyRef.current.contains(e.target)) {
        setShowCompanyDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  const filteredCompanies = companyFilter
    ? companies.filter((c) => c.toLowerCase().includes(companyFilter.toLowerCase()))
    : companies;

  function handleSearch(e) {
    e.preventDefault();
    const params = new URLSearchParams();
    if (keyword.trim()) params.set('keyword', keyword.trim());
    if (location.trim()) params.set('location', location.trim());
    if (company) params.set('company', company);
    navigate(`/jobs${params.toString() ? `?${params.toString()}` : ''}`);
  }

  function handleCompanyClick(name) {
    navigate(`/jobs?company=${encodeURIComponent(name)}`);
  }

  function selectCompany(name) {
    setCompany(name);
    setCompanyFilter(name);
    setShowCompanyDropdown(false);
  }

  return (
    <main>
      <section className="border-b bg-white">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
          <div className="mx-auto max-w-2xl text-center">
            <span
              className="inline-flex items-center rounded-full border bg-accent-50 px-3 py-1 text-xs font-medium text-accent-700"
              style={{ animation: 'fade-in-down 0.5s ease-out both' }}
            >
              Job listing portal
            </span>
            <h1
              className="mt-6 text-4xl font-bold tracking-tight text-ink sm:text-5xl lg:text-6xl"
              style={{ animation: 'fade-in-up 0.6s ease-out 0.15s both' }}
            >
              Find your next{' '}
              <span className="text-accent-600">opportunity</span>
            </h1>
            <p
              className="mt-4 text-base leading-relaxed text-ink-secondary sm:text-lg"
              style={{ animation: 'fade-in-up 0.6s ease-out 0.3s both' }}
            >
              Search thousands of jobs from the world&apos;s best companies.
            </p>
          </div>

          <div
            style={{ animation: 'scale-in 0.5s ease-out 0.45s both' }}
          >
            <form
              onSubmit={handleSearch}
              className="mx-auto mt-8 max-w-3xl rounded-xl border bg-white p-2 shadow-search sm:flex sm:items-center sm:gap-0"
            >
              <div className="flex-1 border-b sm:border-b-0 sm:border-r">
                <label className="sr-only" htmlFor="hero-keyword">
                  Job title or keyword
                </label>
                <input
                  id="hero-keyword"
                  type="text"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="Job title or keyword"
                  className="w-full rounded-lg border-0 bg-transparent px-4 py-3 text-sm text-ink placeholder:text-ink-muted focus:outline-none sm:rounded-r-none"
                />
              </div>
              <div className="flex-1 border-b sm:border-b-0 sm:border-r">
                <label className="sr-only" htmlFor="hero-location">
                  Location
                </label>
                <input
                  id="hero-location"
                  type="text"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Location"
                  className="w-full rounded-lg border-0 bg-transparent px-4 py-3 text-sm text-ink placeholder:text-ink-muted focus:outline-none sm:rounded-none"
                />
              </div>
              <div className="relative flex-1" ref={companyRef}>
                <label className="sr-only" htmlFor="hero-company">
                  Company
                </label>
                <input
                  id="hero-company"
                  type="text"
                  value={companyFilter}
                  onChange={(e) => { setCompanyFilter(e.target.value); setShowCompanyDropdown(true); }}
                  onFocus={() => setShowCompanyDropdown(true)}
                  placeholder="Company"
                  className="w-full rounded-lg border-0 bg-transparent px-4 py-3 text-sm text-ink placeholder:text-ink-muted focus:outline-none"
                />
                {showCompanyDropdown && (
                  <div className="absolute z-10 mt-0 w-full rounded-lg border bg-white shadow-lg">
                    {filteredCompanies.length === 0 ? (
                      <div className="px-3 py-2 text-sm text-ink-muted">No companies found</div>
                    ) : (
                      filteredCompanies.map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => selectCompany(c)}
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
              <div className="p-1 sm:flex-shrink-0">
                <button type="submit" className="btn-primary w-full sm:w-auto">
                  Search
                </button>
              </div>
            </form>
          </div>

          <AnimatedSection delay={0.6} className="mx-auto mt-12 max-w-3xl">
            <p className="mb-3 text-center text-xs font-semibold uppercase tracking-wider text-ink-muted">
              Popular companies
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {companies.map((name, i) => (
                <button
                  key={name}
                  onClick={() => handleCompanyClick(name)}
                  className="rounded-full border bg-white px-4 py-1.5 text-sm font-medium text-ink-secondary transition-all hover:border-accent-500 hover:text-accent-600 hover:shadow-sm"
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
      </section>

      <AnimatedSection delay={0.2}>
        <section className="bg-white">
          <div className="mx-auto max-w-6xl px-4 py-20 text-center sm:px-6">
            <h2 className="text-2xl font-bold text-ink sm:text-3xl">
              Ready to find your next role?
            </h2>
            <p className="mt-2 text-sm text-ink-secondary">
              Start browsing thousands of jobs from top companies right now.
            </p>
            <button
              onClick={() => navigate('/jobs')}
              className="btn-primary mt-6 transition-transform hover:scale-105 active:scale-95"
            >
              Browse all jobs
            </button>
          </div>
        </section>
      </AnimatedSection>
    </main>
  );
}
