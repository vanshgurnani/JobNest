export default function ErrorState({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-50">
        <svg className="h-7 w-7 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <h3 className="mt-4 text-base font-semibold text-ink">Something went wrong</h3>
      <p className="mt-1 text-sm text-ink-secondary">{message || 'Failed to load jobs.'}</p>
      {onRetry && (
        <button onClick={onRetry} className="btn-primary mt-4 text-sm">
          Try again
        </button>
      )}
    </div>
  );
}
