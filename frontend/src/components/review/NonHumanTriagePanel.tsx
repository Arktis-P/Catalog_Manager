import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyNonHumanDecision,
  listNonHumanCandidates,
  type NonHumanCandidate,
  type NonHumanDecisionResult,
} from "../../api/reviewPipeline";
import { pendingReviewImageUrl } from "../../utils/reviewImages";
import { SeriesSearchSelect } from "../SeriesSearchSelect";
import type { Series } from "../../types";
import { LazyReviewImage } from "./LazyReviewImage";
import { ReviewImagePreview } from "./ReviewImagePreview";
import "./reviewPipeline.css";

const PAGE_SIZE = 30;

const DECISION_ACTIONS: Array<{ result: NonHumanDecisionResult; label: string; key: string }> = [
  { result: "non_human", label: "-1 비인간", key: "-" },
  { result: "generation_unavailable", label: "0 생성불가", key: "0" },
  { result: "human_female", label: "3 사람(여)", key: "3" },
  { result: "general_review", label: "일반 리뷰로 이동", key: "u" },
];

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

function humanizeTag(tag: string): string {
  return tag.replace(/_/g, " ");
}

function decisionLabel(result: NonHumanDecisionResult | null): string {
  return DECISION_ACTIONS.find((action) => action.result === result)?.label ?? "";
}

export function NonHumanTriagePanel() {
  const gridRef = useRef<HTMLDivElement>(null);
  const itemsRef = useRef<NonHumanCandidate[]>([]);

  const [items, setItems] = useState<NonHumanCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [reviewFilter, setReviewFilter] = useState<"unreviewed" | "reviewed" | "general_review" | "all">("unreviewed");
  const [category, setCategory] = useState("");
  const [seriesId, setSeriesId] = useState<number | "">("");
  const [search, setSearch] = useState("");
  const [includeCompleted, setIncludeCompleted] = useState(false);

  const [focusIndex, setFocusIndex] = useState(0);
  const [gridCols, setGridCols] = useState(1);
  const [pendingDecisions, setPendingDecisions] = useState<Record<number, NonHumanDecisionResult>>({});
  const [savingIds, setSavingIds] = useState<Set<number>>(() => new Set());
  const [failedMessages, setFailedMessages] = useState<Record<number, string>>({});
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const loadControllerRef = useRef<AbortController | null>(null);
  const loadRequestIdRef = useRef(0);

  const loadItems = useCallback(async () => {
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    const requestId = (loadRequestIdRef.current += 1);
    setLoading(true);
    setError(null);
    try {
      const response = await listNonHumanCandidates(
        {
          review_filter: reviewFilter,
          category: category || undefined,
          series_id: seriesId || undefined,
          search: search || undefined,
          include_completed: includeCompleted,
          skip,
          limit: PAGE_SIZE,
        },
        controller.signal,
      );
      if (loadRequestIdRef.current !== requestId) {
        // A newer request superseded this one; discard the stale result.
        return;
      }
      setItems(response.items);
      setTotal(response.total);
      setFocusIndex((current) => Math.min(current, Math.max(0, response.items.length - 1)));
    } catch (err) {
      if (controller.signal.aborted || loadRequestIdRef.current !== requestId) {
        return;
      }
      setError(err instanceof Error ? err.message : "비인간 후보 목록을 불러오지 못했습니다.");
    } finally {
      if (loadRequestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [reviewFilter, category, seriesId, search, includeCompleted, skip]);

  useEffect(() => {
    void loadItems();
    return () => {
      loadControllerRef.current?.abort();
    };
  }, [loadItems]);

  useEffect(() => {
    setSkip(0);
    setFocusIndex(0);
  }, [reviewFilter, category, seriesId, search, includeCompleted]);

  useEffect(() => {
    const node = gridRef.current;
    if (!node) {
      return;
    }
    const measure = () => {
      const style = window.getComputedStyle(node);
      const cols = style.gridTemplateColumns.split(" ").filter(Boolean).length;
      setGridCols(Math.max(1, cols));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [items.length]);

  const setPendingDecision = useCallback((characterId: number, result: NonHumanDecisionResult) => {
    setPendingDecisions((current) => {
      const next = { ...current };
      if (next[characterId] === result) {
        delete next[characterId];
      } else {
        next[characterId] = result;
      }
      return next;
    });
    setFailedMessages((current) => {
      if (!(characterId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[characterId];
      return next;
    });
  }, []);

  const saveDecision = useCallback(
    async (item: NonHumanCandidate, result: NonHumanDecisionResult) => {
      // Any existing decision, rating, or completed state may be user-owned.
      // Require explicit confirmation before sending overwrite/reopen flags.
      const isReclassification =
        Boolean(item.non_human_review_result) ||
        item.current_rating != null ||
        item.review_status === "completed";
      if (isReclassification) {
        const confirmed = window.confirm(
          `${item.character_tag}은(는) 기존 판정 또는 rating${
            item.non_human_review_result ? `("${item.non_human_review_result}")` : ""
          }이 있습니다.\n` +
            `"${decisionLabel(result)}"(으)로 재분류하면 기존 결정을 덮어쓰고 완료된 리뷰를 다시 엽니다.\n계속할까요?`,
        );
        if (!confirmed) {
          return;
        }
      }

      setSavingIds((current) => new Set(current).add(item.id));
      setFailedMessages((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      setError(null);
      const completedIndex = itemsRef.current.findIndex((entry) => entry.id === item.id);
      try {
        await applyNonHumanDecision(item.id, result, {
          completeReview: true,
          overwriteExisting: isReclassification,
          reopenCompleted: isReclassification,
        });
        setActionMessage(`${item.character_tag} → ${decisionLabel(result)} 저장됨`);
        setPendingDecisions((current) => {
          const next = { ...current };
          delete next[item.id];
          return next;
        });
        if (reviewFilter === "unreviewed") {
          // Saving a decision always moves the item out of the unreviewed bucket,
          // so a local removal is safe and avoids a round-trip.
          const nextItems = itemsRef.current.filter((entry) => entry.id !== item.id);
          setItems(nextItems);
          setTotal((current) => Math.max(0, current - 1));
          setFocusIndex(Math.min(completedIndex >= 0 ? completedIndex : 0, Math.max(0, nextItems.length - 1)));
        } else {
          // Under reviewed/all/general_review the item may still belong in the
          // current list (or a different item may now match), so reconcile
          // against the server instead of guessing at removal/total changes.
          await loadItems();
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "결정 저장에 실패했습니다.";
        setError(message);
        setFailedMessages((current) => ({ ...current, [item.id]: message }));
      } finally {
        setSavingIds((current) => {
          const next = new Set(current);
          next.delete(item.id);
          return next;
        });
      }
    },
    [reviewFilter, includeCompleted, loadItems],
  );

  const focusedItem = items[focusIndex] ?? null;
  const focusedLocked = focusedItem ? savingIds.has(focusedItem.id) : false;
  const previewSrc = focusedItem?.preview_image ? pendingReviewImageUrl(focusedItem.preview_image.image_path) : null;

  useEffect(() => {
    if (!previewSrc) {
      setPreviewOpen(false);
    }
  }, [previewSrc]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target) || !focusedItem) {
        return;
      }

      if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        if (previewSrc) {
          setPreviewOpen((open) => !open);
        }
        return;
      }

      if (previewOpen) {
        // The image preview dialog owns keyboard input (Escape/Tab) while open;
        // background destructive/rating/arrow shortcuts must not also fire.
        return;
      }

      if (focusedLocked) {
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setFocusIndex((index) => Math.max(0, index - 1));
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        setFocusIndex((index) => Math.min(items.length - 1, index + 1));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setFocusIndex((index) => Math.max(0, index - gridCols));
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setFocusIndex((index) => Math.min(items.length - 1, index + gridCols));
        return;
      }

      if (event.key === "-") {
        event.preventDefault();
        setPendingDecision(focusedItem.id, "non_human");
        return;
      }
      if (event.key === "0") {
        event.preventDefault();
        setPendingDecision(focusedItem.id, "generation_unavailable");
        return;
      }
      if (event.key === "3") {
        event.preventDefault();
        setPendingDecision(focusedItem.id, "human_female");
        return;
      }
      if (event.key.toLowerCase() === "u") {
        event.preventDefault();
        setPendingDecision(focusedItem.id, "general_review");
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        const pending = pendingDecisions[focusedItem.id];
        if (pending) {
          void saveDecision(focusedItem, pending);
        }
      }
    };

    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [focusedItem, focusedLocked, gridCols, items.length, pendingDecisions, previewOpen, previewSrc, saveDecision, setPendingDecision]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;

  const filteredSummary = useMemo(
    () => `총 ${total.toLocaleString()}개 · 표시 ${items.length.toLocaleString()}개 · 페이지 ${currentPage}/${pageCount}`,
    [total, items.length, currentPage, pageCount],
  );

  return (
    <>
      <div className="toolbar review-toolbar">
        <div className="field">
          <label htmlFor="nh-filter">상태</label>
          <select
            id="nh-filter"
            value={reviewFilter}
            onChange={(event) => setReviewFilter(event.target.value as typeof reviewFilter)}
          >
            <option value="unreviewed">미검토</option>
            <option value="reviewed">검토됨</option>
            <option value="general_review">일반 리뷰로 이동됨</option>
            <option value="all">전체</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="nh-category">카테고리</label>
          <input id="nh-category" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="series/tag/gender" />
        </div>
        <div className="field">
          <label htmlFor="nh-search">검색</label>
          <input id="nh-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="character tag" />
        </div>
        <div className="field review-series-field">
          <label>시리즈</label>
          <SeriesSearchSelect value={seriesId} onChange={(id: number | "", _series?: Series | null) => setSeriesId(id)} />
        </div>
        <div className="field">
          <label htmlFor="nh-include-completed">&nbsp;</label>
          <label className="review-checkbox-field">
            <input
              id="nh-include-completed"
              type="checkbox"
              checked={includeCompleted}
              onChange={(event) => setIncludeCompleted(event.target.checked)}
            />
            완료 항목 포함
          </label>
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadItems()}>
            새로고침
          </button>
        </div>
        <div className="rp-panel-summary">
          <span>{filteredSummary}</span>
          <span>-/0/3 결정 선택 · u 일반 리뷰로 이동 · Enter 저장/다음 · Space 확대</span>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {actionMessage ? <div className="catalog-card-subtitle" style={{ marginBottom: 8 }}>{actionMessage}</div> : null}

      {loading ? (
        <div className="empty-state">비인간 후보를 불러오는 중...</div>
      ) : items.length === 0 ? (
        <div className="empty-state panel">비인간 후보가 없습니다.</div>
      ) : (
        <div ref={gridRef} className="nh-grid">
          {items.map((item, index) => {
            const focused = index === focusIndex;
            const saving = savingIds.has(item.id);
            const pending = pendingDecisions[item.id] ?? null;
            const failedMessage = failedMessages[item.id];
            const alreadyDecided = Boolean(item.non_human_review_result);
            return (
              <article
                key={item.id}
                data-row-index={index}
                tabIndex={focused ? 0 : -1}
                className={`nh-card${focused ? " nh-card--focused" : ""}${saving ? " nh-card--locked" : ""}${
                  alreadyDecided ? " nh-card--decided" : ""
                }`}
                aria-label={`${item.display_name}, score ${item.score}`}
                onMouseDown={() => setFocusIndex(index)}
                onFocus={() => setFocusIndex(index)}
              >
                <div className="nh-card-image">
                  {item.preview_image ? (
                    <LazyReviewImage
                      imagePath={item.preview_image.image_path}
                      alt={item.character_tag}
                      active={focused}
                      eager
                      thumbSize={256}
                    />
                  ) : (
                    <div className="review-image-slot review-image-slot--empty">
                      <span className="review-image-placeholder">No image</span>
                    </div>
                  )}
                </div>
                <div className="nh-card-body">
                  <div className="nh-card-title-row">
                    <h3 className="nh-card-title">{humanizeTag(item.display_name)}</h3>
                    <span className="nh-score">score {item.score.toFixed(2)}</span>
                  </div>
                  <div className="catalog-card-subtitle">
                    {item.character_tag} · {item.post_count.toLocaleString()} posts
                  </div>
                  <div className="nh-reasons">
                    {item.reasons.slice(0, 4).map((reason) => (
                      <span key={reason} className="pc-reason-chip">
                        {reason}
                      </span>
                    ))}
                  </div>
                  {alreadyDecided ? (
                    <span className="nh-decision-badge">
                      기존 결정: {item.non_human_review_result}
                      {reviewFilter !== "unreviewed" ? " · 재분류 시 확인 필요" : ""}
                    </span>
                  ) : null}
                  <div className="nh-actions">
                    {DECISION_ACTIONS.map((action) => (
                      <button
                        key={action.result}
                        type="button"
                        className={`btn btn-small nh-action-btn${pending === action.result ? " nh-action-btn--active" : ""}`}
                        disabled={saving}
                        onClick={() => setPendingDecision(item.id, action.result)}
                      >
                        {action.label}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary btn-small"
                    disabled={saving || !pending}
                    onClick={() => pending && void saveDecision(item, pending)}
                  >
                    {saving ? "저장 중..." : "저장 (Enter)"}
                  </button>
                  {failedMessage ? <div className="rp-error catalog-card-subtitle">{failedMessage}</div> : null}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {previewOpen && previewSrc && focusedItem ? (
        <ReviewImagePreview
          src={previewSrc}
          alt={focusedItem.character_tag}
          original
          onClose={() => setPreviewOpen(false)}
          characterId={focusedItem.id}
          characterTag={focusedItem.character_tag}
        />
      ) : null}

      {total > PAGE_SIZE ? (
        <div className="series-pagination">
          <div className="series-pagination-controls">
            <button className="btn btn-small" type="button" disabled={skip === 0} onClick={() => setSkip(0)}>
              &laquo;
            </button>
            <button
              className="btn btn-small"
              type="button"
              disabled={skip === 0}
              onClick={() => setSkip((s) => Math.max(0, s - PAGE_SIZE))}
            >
              &lsaquo;
            </button>
            <span className="series-pagination-page-total">
              {currentPage} / {pageCount}
            </span>
            <button
              className="btn btn-small"
              type="button"
              disabled={currentPage >= pageCount}
              onClick={() => setSkip((s) => Math.min((pageCount - 1) * PAGE_SIZE, s + PAGE_SIZE))}
            >
              &rsaquo;
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
