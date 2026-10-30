import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { triggerScrape, triggerScrapeAsync, getScrapeStatus, resolveCompany, fetchScraperHealth } from '../services/api';
import JobCard from '../components/JobCard';
import logger from '../utils/logger';

const POPULAR_PRESETS = [
  { name: 'Stripe', input: 'stripe', ats: 'Greenhouse' },
  { name: 'Notion', input: 'notion', ats: 'Ashby' },
  { name: 'Datadog', input: 'datadog', ats: 'Greenhouse' },
  { name: 'Airbnb', input: 'airbnb', ats: 'Greenhouse' },
  { name: 'Barclays', input: 'barclays', ats: 'Workday' },
  { name: 'Gitlab', input: 'gitlab', ats: 'Greenhouse' },
];

export default function ScraperStudioPage() {
  const [targetInput, setTargetInput] = useState('');
  const [pages, setPages] = useState(1);
  const [saveToDb, setSaveToDb] = useState(true);
  const [isScraping, setIsScraping] = useState(false);
  const [resolvedInfo, setResolvedInfo] = useState(null);
  const [isResolving, setIsResolving] = useState(false);
  const [scrapedJobs, setScrapedJobs] = useState([]);
  const [statusMessage, setStatusMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [healthRecords, setHealthRecords] = useState([]);
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    loadHealth();
  }, []);

  async function loadHealth() {
    try {
      const data = await fetchScraperHealth();
      setHealthRecords(data.records || []);
    } catch (err) {
      logger.warn('ScraperStudio', `Could not load health: ${err.message}`);
    }
  }

  async function handleResolve(value) {
    const val = (value || targetInput).trim();
    if (!val) {
      setResolvedInfo(null);
      return;
    }
    setIsResolving(true);
    try {
      const res = await resolveCompany(val);
      setResolvedInfo(res);
      logger.info('ScraperStudio', `Resolved ${val} -> ${JSON.stringify(res)}`);
    } catch (err) {
      logger.warn('ScraperStudio', `Resolution failed: ${err.message}`);
    } finally {
      setIsResolving(false);
    }
  }

  function handlePresetClick(preset) {
    setTargetInput(preset.input);
    handleResolve(preset.input);
  }

  async function handleStartScrape(e) {
    e?.preventDefault();
    const input = targetInput.trim();
    if (!input) return;

    setIsScraping(true);
    setErrorMessage('');
    setStatusMessage('Initiating automated crawler pipeline...');
    setActiveStep(1);
    setScrapedJobs([]);

    try {
      // Step 1: Resolution & anti-bot handshake
      setActiveStep(2);
      setStatusMessage(`Targeting '${input}' — extracting careers data...`);

      const resp = await triggerScrape({
        input,
        pages,
        saveToDb,
      });

      setActiveStep(3);
      setStatusMessage('Parsing & canonicalizing job payloads...');

      // Find jobs in response structure
      let jobs = [];
      if (resp && resp.results) {
        resp.results.forEach((r) => {
          if (Array.isArray(r.jobs)) {
            jobs.push(...r.jobs);
          }
        });
      } else if (Array.isArray(resp.jobs)) {
        jobs = resp.jobs;
      }

      setActiveStep(4);
      setStatusMessage(`Scrape successful! Found ${jobs.length} jobs.`);
      setScrapedJobs(jobs);

      // Refresh health stats
      loadHealth();
    } catch (err) {
      logger.error('ScraperStudio', `Scrape failed: ${err.message}`);
      setErrorMessage(err.message || 'Scraping failed. Site may be rate-limited or blocked.');
      setActiveStep(0);
    } finally {
      setIsScraping(false);
    }
  }

  return (
    <main className="min-h-screen bg-surface-secondary py-10 px-4 sm:px-6">
      <div className="mx-auto max-w-6xl space-y-8">
        {/* Header */}
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-accent-900 via-accent-800 to-indigo-950 p-8 text-white shadow-xl">
          <div className="relative z-10 max-w-2xl">
            <span className="inline-block rounded-full bg-accent-500/20 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-accent-300">
              ⚡ Automated Pipeline
            </span>
            <h1 className="mt-3 text-3xl font-bold sm:text-4xl">Scraper Studio</h1>
            <p className="mt-2 text-accent-100 text-sm sm:text-base leading-relaxed">
              Send any company name or careers URL. JobNest identifies the ATS (Greenhouse, Lever, Workday, Ashby),
              applies anti-bot rotation, falls back to headless Playwright when JS-rendered, and populates live jobs.
            </p>
          </div>
        </div>

        {/* Input & Control Card */}
        <div className="card p-6 sm:p-8 space-y-6">
          <h2 className="text-xl font-bold text-ink">Target Company or Careers URL</h2>

          <form onSubmit={handleStartScrape} className="space-y-4">
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative flex-1">
                <input
                  type="text"
                  value={targetInput}
                  onChange={(e) => setTargetInput(e.target.value)}
                  onBlur={() => handleResolve()}
                  placeholder="Enter company name (e.g. stripe, notion) or paste careers URL..."
                  className="input-field text-base py-3 pr-24"
                  disabled={isScraping}
                />
                {isResolving && (
                  <span className="absolute right-3 top-3.5 text-xs text-ink-muted animate-pulse">
                    Detecting ATS...
                  </span>
                )}
              </div>

              <button
                type="submit"
                disabled={isScraping || !targetInput.trim()}
                className="btn-primary py-3 px-8 text-base font-semibold shadow-md flex items-center justify-center gap-2 whitespace-nowrap"
              >
                {isScraping ? (
                  <>
                    <svg className="h-5 w-5 animate-spin text-white" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    <span>Ingesting...</span>
                  </>
                ) : (
                  <>
                    <span>⚡ Scrape Now</span>
                  </>
                )}
              </button>
            </div>

            {/* Quick Presets */}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="text-xs font-medium text-ink-muted mr-1">Quick Test:</span>
              {POPULAR_PRESETS.map((preset) => (
                <button
                  key={preset.name}
                  type="button"
                  onClick={() => handlePresetClick(preset)}
                  className="inline-flex items-center gap-1.5 rounded-lg border bg-surface-tertiary px-3 py-1 text-xs font-medium text-ink hover:bg-accent-50 hover:border-accent-300 transition-colors"
                >
                  <span>{preset.name}</span>
                  <span className="text-[10px] text-ink-muted">({preset.ats})</span>
                </button>
              ))}
            </div>

            {/* Resolution Banner */}
            {resolvedInfo && (
              <div className="mt-4 rounded-xl border border-accent-200 bg-accent-50/60 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-accent-900 text-sm">Target Resolved:</span>
                    <span className="rounded bg-accent-600 px-2 py-0.5 text-xs font-bold text-white uppercase">
                      {resolvedInfo.ats?.platform || resolvedInfo.ats || 'Universal Web'}
                    </span>
                    <span className="text-xs text-accent-700 font-mono">
                      {resolvedInfo.company_name}
                    </span>
                  </div>
                  {resolvedInfo.careers_url && (
                    <p className="text-xs text-ink-muted truncate max-w-xl">
                      URL: <a href={resolvedInfo.careers_url} target="_blank" rel="noreferrer" className="underline">{resolvedInfo.careers_url}</a>
                    </p>
                  )}
                </div>
                <div className="text-xs text-accent-800 font-medium">
                  Method: <span className="font-semibold">{resolvedInfo.discovery_method || 'direct'}</span>
                </div>
              </div>
            )}

            {/* Options Row */}
            <div className="flex flex-wrap items-center justify-between gap-4 pt-2 border-t text-sm">
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-ink cursor-pointer">
                  <input
                    type="checkbox"
                    checked={saveToDb}
                    onChange={(e) => setSaveToDb(e.target.checked)}
                    className="rounded text-accent-600 focus:ring-accent-500"
                  />
                  <span>Save directly to MongoDB</span>
                </label>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-ink-muted">Pages:</span>
                {[1, 2, 3].map((num) => (
                  <button
                    key={num}
                    type="button"
                    onClick={() => setPages(num)}
                    className={`h-7 w-7 rounded text-xs font-semibold transition-colors ${
                      pages === num
                        ? 'bg-accent-600 text-white'
                        : 'bg-surface-tertiary text-ink hover:bg-slate-200'
                    }`}
                  >
                    {num}
                  </button>
                ))}
              </div>
            </div>
          </form>

          {/* Progress / Status Display */}
          {(isScraping || statusMessage || errorMessage) && (
            <div className="mt-6 rounded-xl border bg-slate-50 p-5 space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-ink-muted">
                <span>Ingestion Pipeline Status</span>
                {isScraping && <span className="text-accent-600 animate-pulse">Running</span>}
              </div>

              {/* Step indicator */}
              <div className="grid grid-cols-4 gap-2 text-center text-xs">
                <div className={`p-2 rounded ${activeStep >= 1 ? 'bg-accent-600 text-white font-medium' : 'bg-slate-200 text-slate-500'}`}>
                  1. Discovery
                </div>
                <div className={`p-2 rounded ${activeStep >= 2 ? 'bg-accent-600 text-white font-medium' : 'bg-slate-200 text-slate-500'}`}>
                  2. Anti-bot Bypass
                </div>
                <div className={`p-2 rounded ${activeStep >= 3 ? 'bg-accent-600 text-white font-medium' : 'bg-slate-200 text-slate-500'}`}>
                  3. Extraction
                </div>
                <div className={`p-2 rounded ${activeStep >= 4 ? 'bg-emerald-600 text-white font-medium' : 'bg-slate-200 text-slate-500'}`}>
                  4. Complete
                </div>
              </div>

              {statusMessage && (
                <p className="text-sm font-medium text-ink flex items-center gap-2">
                  <span className="inline-block h-2 w-2 rounded-full bg-accent-500" />
                  {statusMessage}
                </p>
              )}

              {errorMessage && (
                <p className="text-sm font-medium text-red-600 bg-red-50 p-3 rounded-lg border border-red-200">
                  {errorMessage}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Results Section */}
        {scrapedJobs.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-ink">
                Scraped Jobs Preview ({scrapedJobs.length})
              </h2>
              <Link to="/jobs" className="text-sm font-semibold text-accent-600 hover:text-accent-700">
                Browse Full Catalog →
              </Link>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {scrapedJobs.map((job, idx) => (
                <JobCard key={job.id || job._id || idx} job={job} />
              ))}
            </div>
          </div>
        )}

        {/* Scraper Health & Reliability Matrix */}
        <div className="card p-6 sm:p-8 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold text-ink">Scraper Reliability Health</h2>
              <p className="text-xs text-ink-muted">
                Circuit breaker and error metrics per target company.
              </p>
            </div>
            <button
              onClick={loadHealth}
              className="btn-ghost text-xs font-semibold text-accent-600 hover:text-accent-700"
            >
              ↻ Refresh
            </button>
          </div>

          {healthRecords.length === 0 ? (
            <p className="text-sm text-ink-muted py-4">No scraper health records recorded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b text-xs uppercase text-ink-muted">
                    <th className="py-3 px-4">Target</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Last Jobs</th>
                    <th className="py-3 px-4">Failures</th>
                    <th className="py-3 px-4">Platform</th>
                    <th className="py-3 px-4">Last Run</th>
                  </tr>
                </thead>
                <tbody className="divide-y text-ink">
                  {healthRecords.map((r) => {
                    const isHealthy = r.status === 'healthy';
                    return (
                      <tr key={r.target} className="hover:bg-slate-50 transition-colors">
                        <td className="py-3 px-4 font-semibold">{r.target}</td>
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                              isHealthy
                                ? 'bg-emerald-100 text-emerald-800'
                                : 'bg-rose-100 text-rose-800'
                            }`}
                          >
                            {r.status}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-mono">{r.last_job_count ?? 0}</td>
                        <td className="py-3 px-4">{r.consecutive_failures ?? 0}</td>
                        <td className="py-3 px-4 text-xs font-medium text-ink-secondary">{r.ats_detected || '—'}</td>
                        <td className="py-3 px-4 text-xs text-ink-muted">
                          {r.last_run ? new Date(r.last_run).toLocaleTimeString() : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
