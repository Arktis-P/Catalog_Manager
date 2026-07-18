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
  // V2 Review가 기본 탭이다. catalog/appearance는 명시적 쿼리로만 진입하고,
  // 그 외 잘못된 mode 값(예: 오타)도 V2로 폴백한다.
  const initialMode = rawMode === "catalog" ? "catalog" : rawMode === "appearance" ? "appearance" : "v2";
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
            V2 Review가 기본 검수 화면입니다. Catalog Review(시리즈 단위 집중 검수)와 Appearance는 탭에서 따로 엽니다.
          </p>
        </div>

        <div className="review-header-tabs">
          <div className="review-mode-tabs" role="tablist" aria-label="Review mode">
            <Link
              className={`review-mode-tab${initialMode === "v2" ? " review-mode-tab--active" : ""}`}
              to="/review?mode=v2"
              role="tab"
              aria-selected={initialMode === "v2"}
            >
              V2
            </Link>
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
