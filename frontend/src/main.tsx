import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { CharacterCatalogJobProvider } from "./context/CharacterCatalogJobContext";
import { CollectJobProvider } from "./context/CollectJobContext";
import { GenerationJobProvider } from "./context/GenerationJobContext";
import { NotificationModeProvider } from "./context/NotificationModeContext";
import { ReviewRegenerateProvider } from "./context/ReviewRegenerateContext";
import "./styles/global.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <NotificationModeProvider>
          <CollectJobProvider>
            <CharacterCatalogJobProvider>
              <GenerationJobProvider>
                <ReviewRegenerateProvider>
                  <App />
                </ReviewRegenerateProvider>
              </GenerationJobProvider>
            </CharacterCatalogJobProvider>
          </CollectJobProvider>
        </NotificationModeProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
);
