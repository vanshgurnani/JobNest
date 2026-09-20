import { useEffect, useMemo, useState } from 'react';
import {
  discoverPortal,
  getCompanies,
  getJobs,
  getMetrics,
  getRun,
  getRuns,
  startRun,
  stopRun,
} from './api';

const NAV = [
  ['/', 'Overview', '▦'],
  ['/companies', 'Companies', '⌘'],
  ['/runs', 'Crawl runs', '↻'],
  ['/jobs', 'Discovered jobs', '▤'],
  ['/errors', 'Errors', '!'],
  ['/portals', 'Portals / ATS', '◈'],
];

const DEFAULT_CONFIG = {
  companies: '', companyUrl: '', mode: 'local', pages: 2, pageSize: 20,
  delaySeconds: 0.5, concurrency: 1, keyword: '', location: '',
};

function readProfiles() {
  try { return JSON.parse(localStorage.getItem('job-nest-scraper-profiles') || '{}'); }
  catch { return {}; }
}

function saveProfiles(value) {
  localStorage.setItem('job-nest-scraper-profiles', JSON.stringify(value));
}

function navigate(path) {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function statusTone(status) {
  if (['completed', 'healthy', 'ok'].includes(status)) return 'success';
  if (['running', 'pending', 'discovering'].includes(status)) return 'info';
  if (['failed', 'error'].includes(status)) return 'danger';
  if (['cancelled', 'partial'].includes(status)) return 'warning';
  return 'neutral';
}

function Badge({ children, tone = 'neutral' }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function Card({ children, className = '' }) {
  return <section className={`panel ${className}`}>{children}</section>;
}

function Stat({ label, value, detail, tone = 'blue' }) {
  return <div className="stat-card">
    <div className={`stat-icon stat-${tone}`}>{tone === 'green' ? '✓' : tone === 'red' ? '!' : tone === 'amber' ? '◌' : '◫'}</div>
    <div><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-detail">{detail}</div></div>
  </div>;
}

function Empty({ title, body, action, onAction }) {
  return <div className="empty"><div className="empty-mark">◌</div><h3>{title}</h3><p>{body}</p>{action && <button className="button primary" onClick={onAction}>{action}</button>}</div>;
}

function Header({ eyebrow, title, body, action, onAction }) {
  return <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{body && <p>{body}</p>}</div>{action && <button className="button primary" onClick={onAction}>＋ {action}</button>}</div>;
}

function Overview({ companies, runs, metrics, onStart }) {
  const summary = metrics?.scrape_summary || {};
  const failed = Object.values(summary).reduce((sum, item) => sum + (item.failures || 0), 0);
  const jobs = companies.reduce((sum, company) => sum + (company.count || 0), 0);
  const running = runs.filter((run) => ['running', 'pending'].includes(run.status)).length;
  const attention = failed + runs.filter((run) => run.status === 'failed').length;
  return <>
    <Header eyebrow="Scraper control center" title="Crawl overview" body="Discover, run, and monitor company career-page ingestion from one place." action="New crawl" onAction={onStart} />
    <div className="stat-grid">
      <Stat label="Companies" value={companies.length.toLocaleString()} detail="Known career sources" />
      <Stat label="Active jobs" value={jobs.toLocaleString()} detail="From indexed companies" tone="green" />
      <Stat label="Crawling now" value={running} detail="In-process runs" tone="amber" />
      <Stat label="Failed crawls" value={attention} detail="Needs attention" tone="red" />
    </div>
    <div className="two-column">
      <Card><div className="panel-heading"><div><h2>Recent activity</h2><p>Runs from this API process</p></div><button className="text-button" onClick={() => navigate('/runs')}>View all →</button></div>
        {runs.length === 0 ? <Empty title="No crawl runs yet" body="Start a local or database-backed crawl to see activity here." action="Start a crawl" onAction={onStart} /> : <RunTable runs={runs.slice(0, 6)} />}
      </Card>
      <Card><div className="panel-heading"><div><h2>System posture</h2><p>What the control center can currently observe</p></div></div>
        <div className="posture-list"><div><span className="posture-dot green" />HTTP-first crawling enabled</div><div><span className="posture-dot green" />Provider detection and fallback adapters</div><div><span className="posture-dot green" />Local and MongoDB persistence modes</div><div><span className="posture-dot amber" />Run history is process-local until persisted</div></div>
      </Card>
    </div>
  </>;
}

function RunTable({ runs, compact = false }) {
  return <div className="table-wrap"><table><thead><tr><th>Target</th><th>Mode</th><th>Status</th><th>Jobs</th><th>Progress</th>{!compact && <th />}</tr></thead><tbody>
    {runs.map((run) => <tr key={run.task_id} onClick={() => navigate(`/runs/${run.task_id}`)} className="clickable"><td><strong>{run.target || 'Unknown target'}</strong><small>{run.task_id}</small></td><td><Badge tone={run.mode === 'db' ? 'info' : 'neutral'}>{run.mode === 'db' ? 'Database' : 'Local'}</Badge></td><td><Badge tone={statusTone(run.status)}>{run.status}</Badge></td><td>{(run.total || 0).toLocaleString()}</td><td><div className="progress-row"><div className="progress"><i style={{ width: `${Math.round((run.progress || 0) * 100)}%` }} /></div><span>{Math.round((run.progress || 0) * 100)}%</span></div></td>{!compact && <td className="arrow">→</td>}</tr>)}
  </tbody></table></div>;
}

function Companies({ companies, profiles, onProfile, onStart }) {
  const [query, setQuery] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({ company: '', domain: '', careerUrl: '' });
  const [discovery, setDiscovery] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const all = useMemo(() => {
    const map = {};
    companies.forEach((item) => { map[item.name.toLowerCase()] = { ...item }; });
    Object.values(profiles).forEach((profile) => {
      const key = (profile.company || profile.name || '').toLowerCase();
      map[key] = { ...(map[key] || {}), ...profile, name: profile.company || profile.name };
    });
    return Object.values(map).filter(Boolean);
  }, [companies, profiles]);
  const filtered = all.filter((item) => `${item.name} ${item.domain || ''} ${item.careers_url || ''} ${item.provider || ''}`.toLowerCase().includes(query.toLowerCase()));

  async function discover(event) {
    event.preventDefault(); setBusy(true); setError('');
    try { const result = await discoverPortal(form); setDiscovery(result); } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  function saveDiscovery() {
    const d = discovery?.discovery || {}; const p = discovery?.detection || {};
    const key = (form.company || d.company || 'company').toLowerCase();
    onProfile(key, { company: form.company || d.company, domain: d.official_domain, careers_url: d.careers_url, provider: p.provider, confidence: p.confidence, capabilities: p.capabilities || [], signals: p.signals || [] });
    setFormOpen(false); setDiscovery(null); setForm({ company: '', domain: '', careerUrl: '' });
  }
  return <>
    <Header eyebrow="Sources" title="Companies" body="Manage career sources and verify portal detection before crawling." action="Add company" onAction={() => setFormOpen(true)} />
    <Card><div className="toolbar"><input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search company, domain, provider…" /><span className="muted">{filtered.length} sources</span></div>
      {filtered.length ? <div className="table-wrap"><table><thead><tr><th>Company</th><th>Career URL</th><th>Portal / ATS</th><th>Jobs</th><th>Health</th><th /></tr></thead><tbody>{filtered.map((item) => <tr key={item.name} className="clickable" onClick={() => onProfile(item.name.toLowerCase(), item)}><td><strong>{item.name}</strong><small>{item.domain || 'Domain not discovered'}</small></td><td className="url-cell">{item.careers_url || 'Needs discovery'}</td><td><Badge tone={item.provider ? 'info' : 'neutral'}>{item.provider || 'Unknown'}</Badge></td><td>{item.count == null ? '—' : item.count.toLocaleString()}</td><td><Badge tone={item.provider ? 'success' : 'warning'}>{item.provider ? 'Ready' : 'Needs discovery'}</Badge></td><td className="arrow">→</td></tr>)}</tbody></table></div> : <Empty title="No companies match" body="Try another search or add a company." action="Add company" onAction={() => setFormOpen(true)} />}
    </Card>
    {formOpen && <Modal title="Add company" onClose={() => setFormOpen(false)}><form onSubmit={discover} className="form-stack"><label>Company name<input className="input" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} placeholder="Stripe" /></label><label>Company domain<input className="input" value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} placeholder="stripe.com" /></label><label>Career URL <span className="muted">(optional)</span><input className="input" value={form.careerUrl} onChange={(e) => setForm({ ...form, careerUrl: e.target.value })} placeholder="https://stripe.com/jobs" /></label>{error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="button secondary" onClick={() => setFormOpen(false)}>Cancel</button><button className="button primary" disabled={busy}>{busy ? 'Discovering…' : 'Discover portal'}</button></div></form>{discovery && <div className="discovery-result"><div className="eyebrow">Discovery complete</div><h3>{discovery.discovery?.company || form.company}</h3><p className="url-cell">{discovery.discovery?.careers_url}</p><div className="result-grid"><div><span>Provider</span><strong>{discovery.detection?.provider || 'Unknown'}</strong></div><div><span>Confidence</span><strong>{Math.round((discovery.detection?.confidence || 0) * 100)}%</strong></div></div><div className="chip-list">{(discovery.detection?.capabilities || []).map((capability) => <Badge key={capability} tone="success">✓ {capability.replaceAll('_', ' ')}</Badge>)}</div><button className="button primary full" onClick={saveDiscovery}>Save source profile</button></div>}</Modal>}
  </>;
}

function Modal({ title, children, onClose }) {
  return <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><div className="modal"><div className="modal-title"><h2>{title}</h2><button className="icon-button" onClick={onClose}>×</button></div>{children}</div></div>;
}

function RunConfig({ initial = {}, onClose, onStarted }) {
  const [config, setConfig] = useState({ ...DEFAULT_CONFIG, ...initial }); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(event) { event.preventDefault(); setBusy(true); setError(''); try { const id = await startRun(config); onStarted(id); } catch (err) { setError(err.message); setBusy(false); } }
  return <Modal title="Configure crawl" onClose={onClose}><form className="form-stack" onSubmit={submit}><div className="mode-switch"><button type="button" className={config.mode === 'local' ? 'selected' : ''} onClick={() => setConfig({ ...config, mode: 'local' })}><strong>Local mode</strong><span>Preview results without MongoDB persistence</span></button><button type="button" className={config.mode === 'db' ? 'selected db' : ''} onClick={() => setConfig({ ...config, mode: 'db' })}><strong>Database mode</strong><span>Persist normalized jobs to MongoDB</span></button></div><label>Company names <span className="muted">comma separated</span><input className="input" value={config.companies} onChange={(e) => setConfig({ ...config, companies: e.target.value })} placeholder="google, stripe" /></label><label>Career URL <span className="muted">optional</span><input className="input" value={config.companyUrl} onChange={(e) => setConfig({ ...config, companyUrl: e.target.value })} placeholder="https://company.com/careers" /></label><div className="form-grid"><label>Pages<input className="input" type="number" min="1" max="100" value={config.pages} onChange={(e) => setConfig({ ...config, pages: e.target.value })} /></label><label>Page size<input className="input" type="number" min="1" max="100" value={config.pageSize} onChange={(e) => setConfig({ ...config, pageSize: e.target.value })} /></label><label>Delay (seconds)<input className="input" type="number" min="0" step="0.1" value={config.delaySeconds} onChange={(e) => setConfig({ ...config, delaySeconds: e.target.value })} /></label><label>Concurrency<input className="input" type="number" min="1" max="10" value={config.concurrency} onChange={(e) => setConfig({ ...config, concurrency: e.target.value })} /></label></div>{error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button className="button primary" disabled={busy}>{busy ? 'Starting…' : 'Start crawl'}</button></div></form></Modal>;
}

function Runs({ runs, onStart }) {
  return <><Header eyebrow="Operations" title="Crawl runs" body="Track active, completed, and failed scraper executions." action="New crawl" onAction={onStart} /><Card>{runs.length ? <RunTable runs={runs} /> : <Empty title="No runs recorded" body="Run history is kept by the current API process." action="Start a crawl" onAction={onStart} />}</Card></>;
}

function JobPreview({ jobs, mode }) {
  return <Card className="preview-card"><div className="panel-heading"><div><h2>Verification preview</h2><p>First five jobs returned by this {mode === 'db' ? 'database' : 'local'} crawl</p></div><Badge tone={jobs.length ? 'success' : 'neutral'}>{jobs.length}/5 visible</Badge></div>{jobs.length ? <div className="preview-list">{jobs.slice(0, 5).map((job, index) => <div className="preview-job" key={job.id || job.job_id || `${job.title}-${index}`}><div className="preview-number">{index + 1}</div><div className="preview-main"><strong>{job.title || 'Untitled job'}</strong><span>{job.company || 'Unknown company'}{job.location ? ` · ${job.location}` : ''}</span><small>{job.portal || mode === 'db' ? job.portal || 'persisted' : 'local preview'}</small></div>{job.apply_url && <a className="text-button" href={job.apply_url} target="_blank" rel="noreferrer">Open →</a>}</div>)}</div> : <Empty title="No jobs available yet" body="Jobs will appear here as the worker completes a target. This preview is limited to five records." />}</Card>;
}

function RunDetail({ id, onBack }) {
  const [run, setRun] = useState(null); const [error, setError] = useState('');
  useEffect(() => { let timer; let active = true; async function load() { try { const data = await getRun(id); if (active) { setRun(data); if (!['completed', 'failed', 'cancelled'].includes(data.status)) timer = setTimeout(load, 2500); } } catch (err) { if (active) setError(err.message); } } load(); return () => { active = false; clearTimeout(timer); }; }, [id]);
  if (error) return <><button className="text-button" onClick={onBack}>← Back</button><div className="inline-error page-error">{error}</div></>;
  if (!run) return <div className="loading">Loading run…</div>;
  const done = ['completed', 'failed', 'cancelled'].includes(run.status); const stages = [['Discovery', run.progress > 0 ? 100 : 0], ['Portal detection', run.progress > 0 ? 100 : 0], ['Job discovery', Math.round((run.progress || 0) * 100)], ['Persistence', run.mode === 'db' ? Math.round((run.progress || 0) * 100) : 0]]; const previewJobs = run.preview_jobs || (run.results || []).flatMap((item) => item.jobs || []).slice(0, 5);
  return <><button className="text-button back-button" onClick={onBack}>← Back to runs</button><div className="page-header"><div><div className="eyebrow">Run {run.task_id}</div><h1>{run.target || 'Scraper run'}</h1><p>{run.mode === 'db' ? 'Database mode · results are persisted to MongoDB' : 'Local mode · results remain in this run'}</p></div><div className="header-actions"><Badge tone={statusTone(run.status)}>{run.status}</Badge>{!done && <button className="button danger" onClick={() => stopRun(id).then(() => getRun(id).then(setRun))}>Stop run</button>}</div></div><div className="run-summary"><Stat label="Jobs discovered" value={(run.total || 0).toLocaleString()} detail={run.message || 'Waiting for updates'} tone="green" /><Stat label="Progress" value={`${Math.round((run.progress || 0) * 100)}%`} detail={run.status} tone="blue" /><Stat label="Persistence" value={run.mode === 'db' ? 'MongoDB' : 'Local'} detail={run.mode === 'db' ? 'Enabled' : 'Preview only'} tone={run.mode === 'db' ? 'green' : 'amber'} /></div><Card><div className="panel-heading"><div><h2>Pipeline progress</h2><p>Stage-based progress from the scraper worker</p></div></div><div className="stage-list">{stages.map(([name, value]) => <div className="stage" key={name}><div><span>{name}</span><strong>{value}%</strong></div><div className="progress large"><i style={{ width: `${value}%` }} /></div></div>)}</div></Card><JobPreview jobs={previewJobs} mode={run.mode} /><Card><div className="panel-heading"><div><h2>Run output</h2><p>{run.results?.length || 0} target result(s)</p></div></div>{run.results?.length ? <div className="result-list">{run.results.map((item, index) => <div className="result-item" key={`${item.target}-${index}`}><div><strong>{item.target}</strong><span>{item.error || `${item.count || 0} jobs discovered`}</span></div><Badge tone={item.error ? 'danger' : 'success'}>{item.error ? 'Failed' : 'Complete'}</Badge></div>)}</div> : <Empty title="Waiting for worker output" body="The run will report each target as it finishes." />}</Card></>;
}

function Errors({ metrics, runs, onStart }) {
  const errors = [...(metrics?.audit_failures || [])]; runs.forEach((run) => { if (run.error) errors.push({ company: run.target, error: run.error, timestamp: new Date().toISOString() }); });
  return <><Header eyebrow="Reliability" title="Error center" body="Actionable failures from recent crawler activity." /><Card>{errors.length ? <div className="table-wrap"><table><thead><tr><th>Company</th><th>Error</th><th>When</th><th /></tr></thead><tbody>{errors.map((item, index) => <tr key={`${item.company}-${index}`}><td><strong>{item.company || 'Unknown'}</strong><small>{item.strategy || 'scrape'}</small></td><td className="error-cell">{item.error || 'Unknown error'}</td><td>{item.timestamp ? new Date(item.timestamp).toLocaleString() : '—'}</td><td><button className="button small secondary" onClick={onStart}>Retry</button></td></tr>)}</tbody></table></div> : <Empty title="No unresolved errors" body="Recent scraper activity has not reported failures." />}</Card></>;
}

function Portals({ profiles }) {
  const rows = Object.values(profiles); const grouped = rows.reduce((acc, item) => { const key = item.provider || 'unknown'; acc[key] = (acc[key] || 0) + 1; return acc; }, {});
  return <><Header eyebrow="Intelligence" title="Portals / ATS" body="Provider profiles captured during discovery." /><Card>{Object.keys(grouped).length ? <div className="portal-grid">{Object.entries(grouped).sort((a, b) => b[1] - a[1]).map(([provider, count]) => <div className="portal-card" key={provider}><div className="portal-mark">◈</div><div><strong>{provider}</strong><span>{count} company source{count === 1 ? '' : 's'}</span></div><Badge tone="info">Detected</Badge></div>)}</div> : <Empty title="No portal profiles yet" body="Add a company and run discovery to build the provider inventory." action="Go to companies" onAction={() => navigate('/companies')} />}</Card></>;
}

function Jobs() {
  const [filters, setFilters] = useState({ company: '', keyword: '', location: '' }); const [data, setData] = useState({ jobs: [], total: 0 }); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  async function load(event) { event?.preventDefault(); setLoading(true); setError(''); try { const result = await getJobs(filters); setData({ jobs: result.jobs || result.latest_jobs || [], total: result.total || 0 }); } catch (err) { setError(err.message); } finally { setLoading(false); } }
  useEffect(() => { load(); }, []);
  return <><Header eyebrow="Inventory" title="Discovered jobs" body="Search normalized jobs returned by the existing Job Nest API." /><Card><form className="filter-row" onSubmit={load}><input className="input" placeholder="Company" value={filters.company} onChange={(e) => setFilters({ ...filters, company: e.target.value })} /><input className="input" placeholder="Keyword" value={filters.keyword} onChange={(e) => setFilters({ ...filters, keyword: e.target.value })} /><input className="input" placeholder="Location" value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })} /><button className="button primary">Search</button></form>{error && <div className="inline-error">{error}</div>}{loading ? <div className="loading">Loading jobs…</div> : data.jobs.length ? <div className="table-wrap"><table><thead><tr><th>Title</th><th>Company</th><th>Location</th><th>Source</th><th /></tr></thead><tbody>{data.jobs.map((job) => <tr key={job.id || job.job_id}><td><strong>{job.title}</strong><small>{job.job_id || job.id}</small></td><td>{job.company}</td><td>{job.location || '—'}</td><td><Badge tone="neutral">{job.portal || job.source || 'universal'}</Badge></td><td>{job.apply_url && <a className="text-button" href={job.apply_url} target="_blank" rel="noreferrer">Open →</a>}</td></tr>)}</tbody></table></div> : <Empty title="No jobs found" body="Run a database-mode crawl or adjust the filters." />}</Card></>;
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname); const [companies, setCompanies] = useState([]); const [runs, setRuns] = useState([]); const [metrics, setMetrics] = useState(null); const [profiles, setProfiles] = useState(readProfiles); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [runDialog, setRunDialog] = useState(null);
  useEffect(() => { const handler = () => setPath(window.location.pathname); window.addEventListener('popstate', handler); return () => window.removeEventListener('popstate', handler); }, []);
  useEffect(() => { Promise.allSettled([getCompanies(), getRuns(), getMetrics()]).then(([companyResult, runResult, metricResult]) => { if (companyResult.status === 'fulfilled') setCompanies(companyResult.value); if (runResult.status === 'fulfilled') setRuns(runResult.value); if (metricResult.status === 'fulfilled') setMetrics(metricResult.value); const rejected = [companyResult, runResult, metricResult].find((item) => item.status === 'rejected'); if (rejected) setError(rejected.reason.message); setLoading(false); }); }, []);
  function profile(key, value) { const next = { ...profiles, [key]: value }; setProfiles(next); saveProfiles(next); }
  function started(id) { setRunDialog(null); navigate(`/runs/${id}`); setTimeout(() => getRuns().then(setRuns), 500); }
  const detailMatch = path.match(/^\/runs\/([^/]+)/); const section = path === '/' ? 'overview' : path.slice(1).split('/')[0];
  const page = detailMatch ? <RunDetail id={detailMatch[1]} onBack={() => navigate('/runs')} /> : section === 'companies' ? <Companies companies={companies} profiles={profiles} onProfile={profile} onStart={(initial) => setRunDialog(initial || {})} /> : section === 'runs' ? <Runs runs={runs} onStart={() => setRunDialog({})} /> : section === 'jobs' ? <Jobs /> : section === 'errors' ? <Errors metrics={metrics} runs={runs} onStart={() => setRunDialog({})} /> : section === 'portals' ? <Portals profiles={profiles} /> : <Overview companies={companies} runs={runs} metrics={metrics} onStart={() => setRunDialog({})} />;
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark">J</div><div><strong>Job Nest</strong><span>Scraper control</span></div></div><div className="sidebar-label">Workspace</div><nav>{NAV.map(([href, label, icon]) => <button key={href} className={(section === (href === '/' ? 'overview' : href.slice(1)) && !detailMatch) ? 'active' : ''} onClick={() => navigate(href)}><span>{icon}</span>{label}</button>)}</nav><div className="sidebar-footer"><span className="status-pulse" />API connected<div className="sidebar-note">Standalone admin workspace<br />Local + MongoDB modes</div></div></aside><main className="main"><div className="mobile-top"><div className="brand"><div className="brand-mark">J</div><strong>Job Nest Scraper</strong></div></div><div className="content">{loading ? <div className="loading">Loading control center…</div> : <>{error && <div className="notice">Some data could not be loaded: {error}</div>}{page}</>}</div></main>{runDialog !== null && <RunConfig initial={runDialog} onClose={() => setRunDialog(null)} onStarted={started} />}</div>;
}
