import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AppearanceReviewPanel } from "../components/review/AppearanceReviewPanel";
import { CatalogReviewPanel } from "../components/review/CatalogReviewPanel";
import { GlobalCatalogReviewPanel } from "../components/review/GlobalCatalogReviewPanel";
import { ReviewRatingGuide } from "../components/review/ReviewRatingGuide";
import { V2ReviewPanel } from "../components/review/V2ReviewPanel";

export function ReviewPage() {
  const [searchParams] = useSearchParams();
  const [catalogScope, setCatalogScope] = useState<"series" | "characters">(
    searchParams.get("scope") === "series" ? "series" : "characters",
  );
  const rawMode = searchParams.get("mode");
  const initialMode = rawMode === "appearance" ? "appearance" : rawMode === "v2" ? "v2" : "catalog";
  const initialSeriesId = useMemo(() => {
    const raw = searchParams.get("series_id");
    if (!raw) {
      return "";
    }
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : "";
  }, [searchParams]);
  const initialCharacterId = useMemo(() => {
    const raw = searchParams.get("character_id");
    if (!raw) {
      return null;
    }
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [searchParams]);

  return (
    <section className="review-page">
      <header className="page-header review-page-header">
        <div>
          <h1 className="page-title">Review</h1>
          <p className="page-description">
            카탈로그 이미지 검수와 외형 태그 확인을 진행합니다. Catalog Review는 시리즈 단위 집중 검수 모드입니다.
          </p>
        </div>

        <div className="review-header-tabs">
          <div className="review-mode-tabs" role="tablist" aria-label="Review mode">
            <Link
              className={`review-mode-tab${initialMode === "catalog" ? " review-mode-tab--active" : ""}`}
              to="/review?mode=catalog"
              role="tab"
              aria-selected={initialMode === "catalog"}
            >
              Catalog Review
            </Link>
            <Link
              className={`review-mode-tab${initialMode === "appearance" ? " review-mode-tab--active" : ""}`}
              to="/review?mode=appearance"
              role="tab"
              aria-selected={initialMode === "appearance"}
            >
              Appearance
            </Link>
            <Link
              className={`review-mode-tab${initialMode === "v2" ? " review-mode-tab--active" : ""}`}
              to="/review?mode=v2"
              role="tab"
              aria-selected={initialMode === "v2"}
            >
              V2
            </Link>
          </div>

          {initialMode === "catalog" ? (
            <>
              <div className="review-header-tabs-divider" aria-hidden="true" />
              <div className="review-mode-tabs" role="tablist" aria-label="Catalog review scope">
                <button
                  type="button"
                  role="tab"
                  aria-selected={catalogScope === "series"}
                  className={`review-mode-tab${catalogScope === "series" ? " review-mode-tab--active" : ""}`}
                  onClick={() => setCatalogScope("series")}
                >
                  시리즈
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={catalogScope === "characters"}
                  className={`review-mode-tab${catalogScope === "characters" ? " review-mode-tab--active" : ""}`}
                  onClick={() => setCatalogScope("characters")}
                >
                  캐릭터
                </button>
              </div>
            </>
          ) : null}
        </div>
      </header>

      {initialMode !== "v2" ? <ReviewRatingGuide /> : null}

      {initialMode === "catalog" ? (
        catalogScope === "series" ? (
          <CatalogReviewPanel initialSeriesId={initialSeriesId} initialCharacterId={initialCharacterId} />
        ) : (
          <GlobalCatalogReviewPanel initialCharacterId={initialCharacterId} />
        )
      ) : initialMode === "v2" ? (
        <V2ReviewPanel />
      ) : (
        <AppearanceReviewPanel />
      )}
    </section>
  );
}
