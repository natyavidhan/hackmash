import { BrowserRouter, Route, Routes } from "react-router-dom";
import { DetailSheet } from "./components/DetailSheet";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import { ToastProvider } from "./components/Toast";
import { CatalogProvider } from "./lib/catalog";
import { ExplorePage } from "./pages/ExplorePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SourcesPage } from "./pages/SourcesPage";
import { TrackerPage } from "./pages/TrackerPage";

export function App() {
  return (
    <BrowserRouter>
      <CatalogProvider>
        <ToastProvider>
          <a className="skip-link" href="#main">
            Skip to the board
          </a>
          <Header />
          <Routes>
            <Route path="/" element={<ExplorePage />} />
            <Route path="/tracker" element={<TrackerPage />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
          <Footer />
          <DetailSheet />
        </ToastProvider>
      </CatalogProvider>
    </BrowserRouter>
  );
}
