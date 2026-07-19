import React, { useMemo } from 'react';

function truncate(text, max = 140) {
  if (!text) return '';
  const s = String(text).trim();
  if (s.length <= max) return s;
  return s.slice(0, max - 1).trimEnd() + '…';
}

export default function JobCard({ job }) {
  const applyHref = job?.url || '';

  const description = useMemo(() => truncate(job?.description, 160), [job]);

  return (
    <article className="card">
      <div className="card__body">
        <h2 className="card__title">{job?.title || 'Untitled'}</h2>

        <div className="card__meta">
          <div className="chip">
            <span className="chip__label">Company</span>
            <span className="chip__value">{job?.company || '-'}</span>
          </div>
          <div className="chip">
            <span className="chip__label">Location</span>
            <span className="chip__value">{job?.location || '-'}</span>
          </div>
        </div>

        <p className="card__desc">{description}</p>
      </div>

      <div className="card__footer">
        <a
          className="btn btn--primary"
          href={applyHref}
          target="_blank"
          rel="noreferrer"
        >
          Apply
        </a>
      </div>
    </article>
  );
}

