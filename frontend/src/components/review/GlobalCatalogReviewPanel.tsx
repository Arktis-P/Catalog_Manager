import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { CatalogReviewFilterStatus, CatalogReviewItem } from "../../types";
import { appearanceTagChips, defaultEnabledTagKeys, resolveFinalPrompt } from "../../utils/reviewPrompt";
import { CatalogReviewRow, createDraftForItem, type CharacterDraft } from "./CatalogReviewRow";
import { toggleRating } from "./ReviewRatingStars";

const PAGE_SIZE = 30;

export function GlobalCatalogReviewPanel() {
  const [items, setItems] = useState<CatalogReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [filterStatus, setFilterStatus] = useState<CatalogReviewFilterStatus>("pending");
  const [search, setSearch] = useState("");
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<number, CharacterDraft>>({});
  const [submittingId, setSubmittingId] = useState<number | null>(null);
  const [thumbSize, setThumbSize] = useState(384);
  const [quadLayout, setQuadLayout] = useState(false);

  useEffect(() => {
    void api.getSettings().then((settings) => {
      setThumbSize(settings.review_thumbnail_size);
      setQuadLayout(settings.generation_images_per_character > 2);
    });
  }, []);

  const loadReviews = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listCatalogReviewsGlobal({
        filter_status: filterStatus,
        search: search || undefined,
        skip,
        limit: PAGE_SIZE,
      });
      setItems(response.items);
      setTotal(response.total);
      setDrafts(Object.fromEntries(response.items.map((item) => [item.id, createDraftForItem(item)])));
    } catch (err) {
      setError(err instanceof Error ? err.message : "카탈로그 검수 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [filterStatus, search, skip]);

  useEffect(() => {
    void loadReviews();
  }, [loadReviews]);

  useEffect(() => {
    setSkip(0);
  }, [filterStatus, search]);

  const updateDraft = (characterId: number, draft: CharacterDraft) => {
    setDrafts((current) => ({ ...current, [characterId]: draft }));
  };

  const toggleTag = (characterId: number, tagKey: string) => {
    const item = items.find((entry) => entry.id === characterId);
    if (!item) return;
    const current = drafts[characterId] ?? createDraftForItem(item);
    const enabled = new Set(
      current.enabledTags.size > 0 ? current.enabledTags : defaultEnabledTagKeys(appearanceTagChips(item)),
    );
    if (enabled.has(tagKey)) {
      enabled.delete(tagKey);
    } else {
      enabled.add(tagKey);
    }
    updateDraft(characterId, { ...current, enabledTags: enabled });
  };

  const setRating = (characterId: number, value: number) => {
    const item = items.find((entry) => entry.id === characterId);
    if (!item) return;
    const current = drafts[characterId] ?? createDraftForItem(item);
    updateDraft(characterId, { ...current, rating: toggleRating(current.rating, value) });
  };

  const completeItem = async (item: CatalogReviewItem) => {
    const draft = drafts[item.id] ?? createDraftForItem(item);
    const isRatingZero = draft.rating === 0;
    const image = item.images[draft.imageIndex];
    if (!isRatingZero && !image) {
      setActionMessage("선택할 이미지가 없습니다.");
      return;
    }
    const chips = appearanceTagChips(item);
    const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
    const finalPrompt = resolveFinalPrompt(item, { ...draft, enabledTags });

    setSubmittingId(item.id);
    setError(null);
    try {
      await api.completeCatalogReviewGlobal(item.id, {
        cover_image_id: isRatingZero ? null : image!.id,
        gender: draft.gender,
        rating: draft.rating,
        final_prompt: finalPrompt,
      });
      setActionMessage(`${item.character_tag} 완료`);
      await loadReviews();
    } catch (err) {
      setError(err instanceof Error ? err.message : "검수 완료에 실패했습니다.");
    } finally {
      setSubmittingId(null);
    }
  };

  const undoItem = async (item: CatalogReviewItem) => {
    setSubmittingId(item.id);
    setError(null);
    try {
      await api.undoCatalogReviewGlobal(item.id);
      setActionMessage(`${item.character_tag} 되돌림`);
      await loadReviews();
    } catch (err) {
      setError(err instanceof Error ? err.message : "실행 취소에 실패했습니다.");
    } finally {
      setSubmittingId(null);
    }
  };

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;

  return (
    <>
      <div className="toolbar review-toolbar">
        <div className="field">
          <label htmlFor="global-catalog-review-filter">Filter</label>
          <select
            id="global-catalog-review-filter"
            value={filterStatus}
            onChange={(event) => setFilterStatus(event.target.value as CatalogReviewFilterStatus)}
          >
            <option value="pending">Pending</option>
            <option value="completed">Completed</option>
            <option value="all">All with images</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="global-catalog-review-search">Search</label>
          <input
            id="global-catalog-review-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="character tag"
          />
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadReviews()}>
            Refresh
          </button>
        </div>
      </div>

      <div className="catalog-review-progress">
        {items.length.toLocaleString()} / {total.toLocaleString()} 표시 · 페이지 {currentPage}/{pageCount}
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {actionMessage ? <div className="catalog-card-subtitle" style={{ marginBottom: 8 }}>{actionMessage}</div> : null}

      {loading ? (
        <div className="empty-state">Loading catalog reviews...</div>
      ) : items.length === 0 ? (
        <div className="empty-state panel">검수할 캐릭터가 없습니다. (특징 태그 수집 완료 후 이미지 생성이 필요합니다)</div>
      ) : (
        <div className="catalog-review-scroll" style={{ overflowY: "auto" }}>
          {items.map((item, rowIndex) => {
            const draft = drafts[item.id] ?? createDraftForItem(item);
            const locked = submittingId === item.id;
            return (
              <div key={item.id} className="global-catalog-review-row-wrapper">
                <CatalogReviewRow
                  item={item}
                  rowIndex={rowIndex}
                  focused
                  draft={draft}
                  thumbSize={thumbSize}
                  quadLayout={quadLayout}
                  locked={locked}
                  onDraftChange={(next) => updateDraft(item.id, next)}
                  onToggleTag={(tagKey) => toggleTag(item.id, tagKey)}
                  onRate={(value) => setRating(item.id, value)}
                />
                <div className="global-catalog-review-row-actions">
                  <select
                    value={draft.gender ?? ""}
                    disabled={locked}
                    onChange={(event) => updateDraft(item.id, { ...draft, gender: event.target.value || null })}
                  >
                    <option value="">gender ?</option>
                    <option value="1girl">1girl</option>
                    <option value="1boy">1boy</option>
                    <option value="no_humans">no_humans</option>
                  </select>
                  <button
                    className="btn btn-primary btn-small"
                    type="button"
                    disabled={locked}
                    onClick={() => void completeItem(item)}
                  >
                    완료
                  </button>
                  {item.review_status === "completed" ? (
                    <button
                      className="btn btn-small"
                      type="button"
                      disabled={locked}
                      onClick={() => void undoItem(item)}
                    >
                      되돌리기
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {total > PAGE_SIZE ? (
        <div className="series-pagination">
          <div className="series-pagination-controls">
            <button className="btn btn-small" type="button" disabled={skip === 0} onClick={() => setSkip(0)}>«</button>
            <button
              className="btn btn-small"
              type="button"
              disabled={skip === 0}
              onClick={() => setSkip((s) => Math.max(0, s - PAGE_SIZE))}
            >
              ‹
            </button>
            <span className="series-pagination-page-total">{currentPage} / {pageCount}</span>
            <button
              className="btn btn-small"
              type="button"
              disabled={currentPage >= pageCount}
              onClick={() => setSkip((s) => s + PAGE_SIZE)}
            >
              ›
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
