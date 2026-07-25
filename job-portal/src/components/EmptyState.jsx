export default function EmptyState({ keyword, location, onClear }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-accent-50">
        <svg className="h-7 w-7 text-accent-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </div>
      <h3 className="mt-4 text-base font-semibold text-ink">No jobs found</h3>
      <p className="mt-1 text-sm text-ink-secondary">
        {keyword || location
          ? `No results for "${keyword || ''} ${location || ''}". Try a different search.`
          : 'Try adjusting your filters or search for a different company.'}
      </p>
      {(keyword || location) && (
        <button onClick={onClear} className="btn-ghost mt-4 text-sm font-medium text-accent-600">
          Clear search
        </button>
      )}
    </div>
  );
}
