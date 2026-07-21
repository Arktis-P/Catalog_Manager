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
  const modeDescription =
    initialMode === "catalog"
      ? "카탈로그 검수는 시리즈 또는 전체 캐릭터 범위에서 기존 카탈로그 데이터와 대표 이미지를 집중 확인합니다."
      : initialMode === "appearance"
        ? "외형 검수는 캐릭터의 성별, 머리색, 눈색, 특징 태그 같은 외형 메타데이터를 정리합니다."
        : "V2 검수는 새 생성 후보를 빠르게 판정하고, 대표 이미지와 프롬프트 태그를 함께 저장하는 기본 워크플로우입니다.";

  return (
    <section className="review-page">
      <header className="page-header review-page-header">
        <div>
          <h1 className="page-title">리뷰</h1>
          <p className="page-description">
            V2 검수는 기본 화면입니다. 카탈로그 검수와 외형 검수는 기존 URL을 유지한 탭에서 따로 엽니다.
          </p>
          <p className="page-description">{modeDescription}</p>
        </div>

        <div className="review-header-tabs">
          <div className="review-mode-tabs" role="tablist" aria-label="리뷰 모드">
            <Link
              className={`review-mode-tab${initialMode === "v2" ? " review-mode-tab--active" : ""}`}
              to="/review?mode=v2"
              role="tab"
              aria-selected={initialMode === "v2"}
            >
              V2 검수
            </Link>
            <Link
              className={`review-mode-tab${initialMode === "catalog" ? " review-mode-tab--active" : ""}`}
              to="/review?mode=catalog"
              role="tab"
              aria-selected={initialMode === "catalog"}
            >
              카탈로그 검수
            </Link>
            <Link
              className={`review-mode-tab${initialMode === "appearance" ? " review-mode-tab--active" : ""}`}
              to="/review?mode=appearance"
              role="tab"
              aria-selected={initialMode === "appearance"}
            >
              외형 검수
            </Link>
          </div>

          {initialMode === "catalog" ? (
            <>
              <div className="review-header-tabs-divider" aria-hidden="true" />
              <div className="review-mode-tabs" role="tablist" aria-label="카탈로그 검수 범위">
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
