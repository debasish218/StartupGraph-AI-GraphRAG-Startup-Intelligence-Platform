import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { AskPage } from './pages/AskPage';
import { ComparePage } from './pages/ComparePage';
import { DiscoverPage } from './pages/DiscoverPage';
import { ExplorerPage } from './pages/ExplorerPage';
import { IngestPage } from './pages/IngestPage';
import { RankingsPage } from './pages/RankingsPage';
import { AskSessionProvider } from './session';

export default function App() {
  return (
    <AskSessionProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<AskPage />} />
            <Route path="explorer" element={<ExplorerPage />} />
            <Route path="rankings" element={<RankingsPage />} />
            <Route path="discover" element={<DiscoverPage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route path="ingest" element={<IngestPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AskSessionProvider>
  );
}
