import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { fetchJobById } from '../services/api';

function timeAgo(dateStr) {
  if (!dateStr) return null;
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return null;
  const diff = Math.floor((Date.now() - date) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 2592000) return `${Math.floor(diff / 86400)}d ago`;
  return `${Math.floor(diff / 2592000)}mo ago`;
}

export default function JobDetailPage() {
  const { id } = useParams();
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchJobById(id)
      .then((data) => {
        if (!data) throw new Error('Job not found');
        setJob(data);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (!job) return;
    const stored = JSON.parse(localStorage.getItem('savedJobs') || '[]');
    setSaved(stored.includes(job.id || job.job_id));
  }, [job]);

  function handleSave() {
    if (!job) return;
    const stored = JSON.parse(localStorage.getItem('savedJobs') || '[]');
    const jid = job.id || job.job_id;
    if (saved) {
      const next = stored.filter((s) => s !== jid);
      localStorage.setItem('savedJobs', JSON.stringify(next));
      setSaved(false);
    } else {
      stored.push(jid);
      localStorage.setItem('savedJobs', JSON.stringify(stored));
      setSaved(true);
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
        <div className="skeleton mb-8 h-4 w-20 rounded" />
        <div className="skeleton mb-4 h-8 w-3/4 rounded" />
        <div className="skeleton mb-6 h-5 w-1/2 rounded" />
        <div className="space-y-2">
          <div className="skeleton h-4 w-full rounded" />
          <div className="skeleton h-4 w-5/6 rounded" />
          <div className="skeleton h-4 w-4/5 rounded" />
          <div className="skeleton h-4 w-3/4 rounded" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-20 text-center sm:px-6">
        <div className="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-full bg-red-50">
          <svg className="h-7 w-7 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-ink">Unable to load job</h2>
        <p className="mt-1 text-sm text-ink-secondary">{error}</p>
        <Link to="/" className="btn-primary mt-6 inline-flex text-sm">
          Back to jobs
        </Link>
      </div>
    );
  }

  if (!job) return null;

  const ago = timeAgo(job.posted_date || job.date_posted);
  const skills = job.skills || [];

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-12">
      <Link
        to="/"
        className="mb-6 inline-flex items-center gap-1 text-sm font-medium text-ink-secondary hover:text-ink"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to jobs
      </Link>

      <div className="card p-6 sm:p-8">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-xl bg-accent-50 text-lg font-bold text-accent-600">
            {(job.company || '?').charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-bold text-ink sm:text-2xl">{job.title}</h1>
            <p className="mt-1 text-base text-ink-secondary">{job.company}</p>

            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-muted">
              {job.location && (
                <span className="flex items-center gap-1.5">
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  {job.location}
                </span>
              )}
              {job.employment_type && (
                <span className="flex items-center gap-1.5">
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                  </svg>
                  {job.employment_type}
                </span>
              )}
              {job.experience && (
                <span className="flex items-center gap-1.5">
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                  {job.experience}
                </span>
              )}
              {ago && (
                <span className="flex items-center gap-1.5">
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  {ago}
                </span>
              )}
            </div>
          </div>
        </div>

        {skills.length > 0 && (
          <div className="mt-6 flex flex-wrap gap-2">
            {skills.map((skill) => (
              <span key={skill} className="tag">{skill}</span>
            ))}
          </div>
        )}

        <div className="mt-6 flex flex-wrap gap-3">
          <button
            onClick={handleSave}
            className={`btn-outline gap-2 text-sm ${
              saved ? 'border-accent-500 text-accent-600' : ''
            }`}
          >
            <svg className="h-4 w-4" fill={saved ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
            {saved ? 'Saved' : 'Save job'}
          </button>

          {job.apply_url && (
            <a
              href={job.apply_url}
              target="_blank"
              rel="noreferrer"
              className="btn-primary gap-2 text-sm"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              Apply now
            </a>
          )}
        </div>

        <hr className="my-6" />

        <div>
          <h2 className="mb-3 text-base font-semibold text-ink">About this job</h2>
          <div className="prose prose-sm max-w-none text-ink-secondary leading-relaxed whitespace-pre-line">
            {job.description || 'No description was available from the source.'}
          </div>
        </div>

        {job.source && (
          <p className="mt-6 text-xs text-ink-muted">
            Source: {job.source}
            {job.crawled_at && ` · Crawled: ${new Date(job.crawled_at).toLocaleDateString()}`}
          </p>
        )}
      </div>
    </div>
  );
}
