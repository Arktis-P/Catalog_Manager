import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AppearanceReviewPanel } from "../components/review/AppearanceReviewPanel";
import { CatalogReviewPanel } from "../components/review/CatalogReviewPanel";
import { ReviewRatingGuide } from "../components/review/ReviewRatingGuide";

export function ReviewPage() {
  const [searchParams] = useSearchParams();
  const initialMode = searchParams.get("mode") === "appearance" ? "appearance" : "catalog";
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
      <header className="page-header">
        <div>
          <h1 className="page-title">Review</h1>
          <p className="page-description">
            카탈로그 이미지 검수와 외형 태그 확인을 진행합니다. Catalog Review는 시리즈 단위 집중 검수 모드입니다.
          </p>
        </div>
      </header>

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
      </div>

      <ReviewRatingGuide />

      {initialMode === "catalog" ? (
        <CatalogReviewPanel initialSeriesId={initialSeriesId} initialCharacterId={initialCharacterId} />
      ) : (
        <AppearanceReviewPanel />
      )}
    </section>
  );
}
