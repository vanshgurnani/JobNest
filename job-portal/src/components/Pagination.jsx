export default function Pagination({ page, totalPages, onPageChange }) {
  if (totalPages <= 1) return null;

  const pages = [];
  const maxVisible = 5;
  let start = Math.max(1, page - Math.floor(maxVisible / 2));
  let end = Math.min(totalPages, start + maxVisible - 1);
  if (end - start + 1 < maxVisible) {
    start = Math.max(1, end - maxVisible + 1);
  }
  for (let p = start; p <= end; p++) pages.push(p);

  return (
    <nav className="mt-8 flex items-center justify-center gap-1" aria-label="Pagination">
      <button
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="btn-ghost gap-1 rounded-lg px-3 py-2 text-xs disabled:opacity-30"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Previous
      </button>

      {pages[0] > 1 && (
        <>
          <button onClick={() => onPageChange(1)} className="btn-ghost h-8 w-8 rounded-lg p-0 text-xs">
            1
          </button>
          {pages[0] > 2 && <span className="px-1 text-xs text-ink-muted">...</span>}
        </>
      )}

      {pages.map((p) => (
        <button
          key={p}
          onClick={() => onPageChange(p)}
          className={`h-8 w-8 rounded-lg text-xs font-medium transition-colors ${
            p === page
              ? 'bg-accent-600 text-white'
              : 'btn-ghost p-0'
          }`}
        >
          {p}
        </button>
      ))}

      {pages[pages.length - 1] < totalPages && (
        <>
          {pages[pages.length - 1] < totalPages - 1 && (
            <span className="px-1 text-xs text-ink-muted">...</span>
          )}
          <button
            onClick={() => onPageChange(totalPages)}
            className="btn-ghost h-8 w-8 rounded-lg p-0 text-xs"
          >
            {totalPages}
          </button>
        </>
      )}

      <button
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="btn-ghost gap-1 rounded-lg px-3 py-2 text-xs disabled:opacity-30"
      >
        Next
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </button>
    </nav>
  );
}
