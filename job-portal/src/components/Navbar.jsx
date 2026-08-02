import { Link, useLocation } from 'react-router-dom';

export default function Navbar() {
  const location = useLocation();

  return (
    <header className="sticky top-0 z-50 border-b bg-white/90 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-600 text-sm font-bold text-white">
            J
          </div>
          <span className="text-lg font-semibold text-ink">JobBoard</span>
        </Link>

        <nav className="flex items-center gap-1">
          <Link
            to="/"
            className={`btn-ghost text-sm ${location.pathname === '/' ? 'text-accent-600 bg-accent-50' : ''}`}
          >
            Home
          </Link>
          <Link
            to="/jobs"
            className={`btn-ghost text-sm ${location.pathname === '/jobs' ? 'text-accent-600 bg-accent-50' : ''}`}
          >
            Find Jobs
          </Link>
          <Link
            to="/companies"
            className={`btn-ghost text-sm ${location.pathname === '/companies' ? 'text-accent-600 bg-accent-50' : ''}`}
          >
            Companies
          </Link>
        </nav>
      </div>
    </header>
  );
}
