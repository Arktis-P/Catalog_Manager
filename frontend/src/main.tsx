import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { CollectJobProvider } from "./context/CollectJobContext";
import { GenerationJobProvider } from "./context/GenerationJobContext";
import { ReviewRegenerateProvider } from "./context/ReviewRegenerateContext";
import "./styles/global.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <CollectJobProvider>
        <GenerationJobProvider>
          <ReviewRegenerateProvider>
            <App />
          </ReviewRegenerateProvider>
        </GenerationJobProvider>
      </CollectJobProvider>
    </BrowserRouter>
  </StrictMode>,
);
