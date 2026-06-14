import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { CatalogPage } from "./pages/CatalogPage";
import { GenerationPage } from "./pages/GenerationPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SeriesPage } from "./pages/SeriesPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<CatalogPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="series" element={<SeriesPage />} />
        <Route path="generation" element={<GenerationPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
