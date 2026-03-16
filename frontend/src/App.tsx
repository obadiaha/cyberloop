import { Routes, Route } from 'react-router-dom';
import Setup from './pages/Setup';
import Interview from './pages/Interview';
import ReportCard from './pages/ReportCard';

export default function App() {
  return (
    <div className="min-h-screen bg-cyber-bg">
      <Routes>
        <Route path="/" element={<Setup />} />
        <Route path="/interview/:sessionId" element={<Interview />} />
        <Route path="/report/:sessionId" element={<ReportCard />} />
      </Routes>
    </div>
  );
}
