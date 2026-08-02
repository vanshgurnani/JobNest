import { lazy, Suspense, useEffect } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import Navbar from './components/Navbar';
import ErrorBoundary from './components/ErrorBoundary';
import HomePage from './pages/HomePage';
import logger from './utils/logger';

const FindJobsPage = lazy(() => import('./pages/FindJobsPage'));
const JobDetailPage = lazy(() => import('./pages/JobDetailPage'));

function PageLoader() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-200 border-t-blue-600" />
    </div>
  );
}

function RouteLogger() {
  const location = useLocation();
  useEffect(() => {
    logger.info('router', `Navigated to ${location.pathname}${location.search}`);
  }, [location]);
  return null;
}

export default function App() {
  return (
    <div className="min-h-screen bg-surface-secondary">
      <ErrorBoundary>
        <RouteLogger />
        <Navbar />
        <Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/jobs" element={<FindJobsPage />} />
            <Route path="/job/:id" element={<JobDetailPage />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </div>
  );
}
