import { Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import HomePage from './pages/HomePage';
import FindJobsPage from './pages/FindJobsPage';
import JobDetailPage from './pages/JobDetailPage';

export default function App() {
  return (
    <div className="min-h-screen bg-surface-secondary">
      <Navbar />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/jobs" element={<FindJobsPage />} />
        <Route path="/job/:id" element={<JobDetailPage />} />
      </Routes>
    </div>
  );
}
