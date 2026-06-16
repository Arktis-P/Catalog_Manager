import { useState } from "react";
import { AppearanceReviewPanel } from "../components/review/AppearanceReviewPanel";
import { CatalogReviewPanel } from "../components/review/CatalogReviewPanel";

type ReviewMode = "catalog" | "appearance";

export function ReviewPage() {
  const [mode, setMode] = useState<ReviewMode>("catalog");

  return (
    <section className="review-page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Review</h1>
          <p className="page-description">
            카탈로그 이미지 검수와 외형 태그 확인을 진행합니다. Catalog Review는 시리즈 단위 집중 검수 모드입니다.
          </p>
        </div>
      </header>

      <div className="review-mode-tabs" role="tablist" aria-label="Review mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "catalog"}
          className={`review-mode-tab${mode === "catalog" ? " review-mode-tab--active" : ""}`}
          onClick={() => setMode("catalog")}
        >
          Catalog Review
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "appearance"}
          className={`review-mode-tab${mode === "appearance" ? " review-mode-tab--active" : ""}`}
          onClick={() => setMode("appearance")}
        >
          Appearance
        </button>
      </div>

      {mode === "catalog" ? <CatalogReviewPanel /> : <AppearanceReviewPanel />}
    </section>
  );
}
