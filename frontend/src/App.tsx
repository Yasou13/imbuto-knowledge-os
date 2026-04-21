import { HashRouter, Routes, Route, Navigate } from "react-router-dom";

import { MainLayout } from "./app/layouts/MainLayout";
import { EditorPage } from "./pages/EditorPage/EditorPage";
import { QueryEnginePage } from "./pages/QueryEnginePage/QueryEnginePage";
import { GraphPage } from "./pages/GraphPage/GraphPage";
import { IngestPage } from "./pages/IngestPage/IngestPage";

function App() {
  return (
    <HashRouter>
      <MainLayout>
        <Routes>
          <Route path="/" element={<Navigate to="/editor" replace />} />
          <Route path="/editor" element={<EditorPage />} />
          <Route path="/editor/*" element={<EditorPage />} />
          <Route path="/query" element={<QueryEnginePage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/ingest" element={<IngestPage />} />
        </Routes>
      </MainLayout>
    </HashRouter>
  );
}

export default App;

