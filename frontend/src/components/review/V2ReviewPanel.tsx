import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { api } from "../../api/client";
import { useGenerationJobs } from "../../context/GenerationJobContext";
import { CharacterLinkModal } from "../CharacterLinkModal";
import { SeriesSearchSelect } from "../SeriesSearchSelect";
import type {
  LinkableCharacterSummary,
  Series,
  V2GenerationJobState,
  V2ReviewCharacter,
  V2ReviewFilters,
  V2ReviewStats,
  V2ReviewStatus,
  V2NonHumanFilter,
  NonHumanRatingFilter,
} from "../../types";
import {
  cycleGender,
  defaultEnabledTagKeys,
  genderChipClass,
  genderChipLabel,
  hasMulticolorHairTag,
  normalizeHairTags,
} from "../../utils/reviewPrompt";
import { pendingReviewImageUrl } from "../../utils/reviewImages";
import { LazyReviewImage } from "./LazyReviewImage";
import {
  getV2ReviewCardSize,
  getV2ReviewCardWidthPx,
  onV2ReviewCardSettingsChanged,
  resolveV2ReviewCardWidthPx,
  type V2ReviewCardSize,
} from "../../utils/v2ReviewCardSettings";
import {
  createV2DraftForItem,
  resolveV2FinalPrompt,
  v2AppearanceTagChips,
  v2SelectedTagsPayload,
  V2ReviewRow,
  type V2CharacterDraft,
  type V2ReviewCardSaveStatus,
} from "./V2ReviewRow";
import { V2SingleReviewOverlay } from "./V2SingleReviewOverlay";
import { PurgeUnselectedModal } from "./PurgeUnselectedModal";
import { ReviewImagePreview } from "./ReviewImagePreview";
import { toggleRating } from "./ReviewRatingStars";
import { ReviewShortcutGuide } from "./ReviewShortcutGuide";

const PAGE_SIZE = 30;

type SingleReviewSession =
  | { source: "review"; itemId: number }
  | { source: "non_human"; itemId: number };

// Rating decisions live in the shared General Review draft. Only candidate exclusion
// (key e) has no draft equivalent, so it keeps one small mode-specific staged flag.
type NonHumanOverlayDecision = { action: "exclude" };

const V2_RATING_FLOW: Array<{ question: string; result: string }> = [
  { question: "사람 또는 고정된 사람형 캐릭터가 아닌가요? (고정 외형 없는 플레이어 대리 캐릭터 포함)", result: "-1" },
  { question: "레이팅 가능한 이미지 생성에 실패했나요?", result: "0" },
  { question: "boy 캐릭터의 특성이 여전히 강한가요?", result: "1" },
  { question: "완전히 기피하고 싶은 태그가 있나요?", result: "2" },
  { question: "그 외 여성 캐릭터인가요? (기본값)", result: "3" },
  { question: "확실한 고선호인가요? (정말 좋아함 / 최선호)", result: "5 / 6" },
];

function V2RatingGuide() {
  return (
    <details className="review-rating-guide">
      <summary className="review-rating-guide-summary">
        <span className="review-rating-guide-title">V2 1차 레이팅 가이드</span>
        <span className="review-rating-guide-hint">-1/0/1/2/3/5/6 권장 · 4는 1차 리뷰에서 사용하지 않음</span>
      </summary>
      <div className="review-rating-guide-body">
        <ol className="v2-rating-guide-list">
          {V2_RATING_FLOW.map((row) => (
            <li key={row.question}>
              {row.question} <strong>→ {row.result}</strong>
            </li>
          ))}
        </ol>
      </div>
    </details>
  );
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

function toLinkableSummary(item: V2ReviewCharacter): LinkableCharacterSummary {
  return {
    id: item.id,
    character_tag: item.character_tag,
    display_name: item.display_name,
    is_alternative: item.is_alternative,
    parent_character_tag: item.parent_character_tag,
    parent_display_name: item.parent_display_name,
    child_count: item.child_count,
  };
}

function sameStringSet(left: Set<string>, right: Set<string>): boolean {
  return left.size === right.size && Array.from(left).every((value) => right.has(value));
}

function isDraftChanged(item: V2ReviewCharacter, draft: V2CharacterDraft): boolean {
  const initial = createV2DraftForItem(item);
  return (
    draft.imageIndex !== initial.imageIndex ||
    draft.gender !== initial.gender ||
    draft.rating !== initial.rating ||
    draft.customPrompt !== initial.customPrompt ||
    draft.promptEdited !== initial.promptEdited ||
    !sameStringSet(draft.enabledTags, initial.enabledTags)
  );
}

function nonHumanEvidenceLabel(code: string): string {
  return code.replace(/_/g, " ").replace(/:/g, ": ");
}

function nonHumanExistingRatingBadge(rating: number | null): { text: string; className: string; title: string } | null {
  if (rating === null || rating === undefined) {
    return null;
  }
  if (rating === -1) {
    return { text: "-1 ☆", className: "review-rating-status review-rating-status--red", title: "기존 평점 -1" };
  }
  if (rating === 0) {
    return { text: "0 ☆", className: "review-rating-status review-rating-status--zero", title: "기존 평점 0" };
  }
  return {
    text: `${rating} ${"★".repeat(rating)}`,
    className: "review-rating-status review-rating-status--set",
    title: `기존 평점 ${rating}`,
  };
}

interface NonHumanQueueCardProps {
  item: V2ReviewCharacter;
  focused: boolean;
  acting: boolean;
  failedMessage?: string;
  onSelect: () => void;
  onConfirmProposed: () => void;
  onConfirm: (rating: -1 | 3) => void;
  onExclude: () => void;
  onOpenDetails: () => void;
}

function NonHumanQueueCard({
  item,
  focused,
  acting,
  failedMessage,
  onSelect,
  onConfirmProposed,
  onConfirm,
  onExclude,
  onOpenDetails,
}: NonHumanQueueCardProps) {
  const image = item.preview_image;
  const primarySeriesTag = item.series_tags[0] ?? null;
  const suggested = item.non_human_suggested_rating;
  const hasSuggested = suggested === -1 || suggested === 3;
  const cardLabel = `${item.display_name || item.character_tag}, 후보 점수 ${item.non_human_candidate_score.toFixed(2)}`;
  const existingRatingBadge = nonHumanExistingRatingBadge(item.rating);
  const handleKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    const key = event.key.toLowerCase();
    if (!acting && key === "s" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      event.stopPropagation();
      onOpenDetails();
    }
  };

  return (
    <article
      className={`v2-review-card v2-non-human-card${focused ? " v2-review-card--focused" : ""}${acting ? " v2-review-card--locked" : ""}`}
      data-character-id={item.id}
      tabIndex={focused ? 0 : -1}
      aria-current={focused ? "true" : undefined}
      aria-busy={acting}
      aria-label={cardLabel}
      onMouseDown={onSelect}
      onFocus={onSelect}
      onKeyDown={handleKeyDown}
    >
      <div className="v2-review-card-image-wrap">
        {image ? (
          <LazyReviewImage
            imagePath={image.image_path}
            alt={`${item.character_tag} preview`}
            active={focused}
            eager
            thumbSize={320}
          />
        ) : (
          <div className="review-image-slot review-image-slot--empty">
            <span className="review-image-placeholder">No image</span>
          </div>
        )}
      </div>
      <div className="v2-review-card-body">
        <div className="v2-review-card-name-row">
          <h3 className="v2-review-card-name">{item.display_name || item.character_tag}</h3>
          <span className={genderChipClass(item.gender)}>{genderChipLabel(item.gender)}</span>
        </div>
        <div className="v2-review-card-series-row">
          <span className="catalog-card-subtitle">{primarySeriesTag ?? "시리즈 없음"}</span>
          <span className="badge">{item.post_count.toLocaleString()} posts</span>
        </div>
        <div className="v2-non-human-rating-row">
          <span
            className="badge badge-muted badge-compact"
            title={`후보 점수 ${item.non_human_candidate_score.toFixed(2)}`}
          >
            점수 {item.non_human_candidate_score.toFixed(2)}
          </span>
          {existingRatingBadge ? (
            <span className={`${existingRatingBadge.className} badge-compact`} title={existingRatingBadge.title}>
              {existingRatingBadge.text}
            </span>
          ) : (
            <span className="review-rating-status review-rating-status--unset badge-compact" title="기존 평점 없음">
              평점 없음
            </span>
          )}
          {hasSuggested ? (
            <span className="badge badge-warning badge-compact">제안 {suggested}</span>
          ) : (
            <span className="badge badge-muted badge-compact">제안 없음</span>
          )}
        </div>
        {item.non_human_evidence.length > 0 ? (
          <div className="v2-non-human-evidence">
            {item.non_human_evidence.map((code) => (
              <span key={code} className="badge badge-muted">
                {nonHumanEvidenceLabel(code)}
              </span>
            ))}
          </div>
        ) : null}
        {failedMessage ? <div className="v2-non-human-error">{failedMessage}</div> : null}
        <div className="v2-review-card-actions">
          <button
            className="btn btn-small"
            type="button"
            disabled={acting || !hasSuggested}
            title="Enter"
            onClick={onConfirmProposed}
          >
            제안 확정{hasSuggested ? ` (${suggested})` : ""}
          </button>
          <button className="btn btn-small" type="button" disabled={acting} title="-" onClick={() => onConfirm(-1)}>
            -1
          </button>
          <button className="btn btn-small" type="button" disabled={acting} title="3" onClick={() => onConfirm(3)}>
            3
          </button>
          <button className="btn btn-small" type="button" disabled={acting} title="e" onClick={onExclude}>
            제외
          </button>
        </div>
      </div>
    </article>
  );
}

export function V2ReviewPanel() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const focusCardFromKeyboardRef = useRef(false);
  // Dedicated to the non-human queue so arrow-key movement can claim DOM focus
  // without click/filter-driven focusIndex changes stealing it unexpectedly.
  const nhFocusCardFromKeyboardRef = useRef(false);
  const loadedSkipRef = useRef(0);
  const focusIndexRef = useRef(0);
  const [items, setItems] = useState<V2ReviewCharacter[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<V2ReviewStats | null>(null);

  const [reviewStatus, setReviewStatus] = useState<V2ReviewStatus>("pending");
  const [ratingFilter, setRatingFilter] = useState("");
  const [qualityStatus, setQualityStatus] = useState("");
  const [identityStatus, setIdentityStatus] = useState("");
  const [generationStatus, setGenerationStatus] = useState("");
  const [genderFilter, setGenderFilter] = useState("");
  const [nonHumanFilter, setNonHumanFilter] = useState<V2NonHumanFilter>("all");
  const [seriesId, setSeriesId] = useState<number | "">("");
  const [multicolorFilter, setMulticolorFilter] = useState("");
  const [promptModifiedOnly, setPromptModifiedOnly] = useState(false);
  const [search, setSearch] = useState("");

  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, V2CharacterDraft>>({});
  const [dirtyIds, setDirtyIds] = useState<Set<number>>(() => new Set());
  const [savingIds, setSavingIds] = useState<Set<number>>(() => new Set());
  const [failedMessages, setFailedMessages] = useState<Record<number, string>>({});
  const [submittingId, setSubmittingId] = useState<number | null>(null);
  const [bulkSaving, setBulkSaving] = useState(false);
  const [purgeModalOpen, setPurgeModalOpen] = useState(false);
  const [thumbSize, setThumbSize] = useState(384);
  const [cardSize, setCardSize] = useState<V2ReviewCardSize>("medium");
  const [cardWidthPx, setCardWidthPx] = useState(0);
  const [gridCols, setGridCols] = useState(1);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewFit, setPreviewFit] = useState(true);
  const [linkingItem, setLinkingItem] = useState<V2ReviewCharacter | null>(null);
  // The link modal is shared by both tabs (opened from the general grid, its keyboard
  // 'a', or the non-human overlay's 'a'); tracks which list to reload once linked.
  const [linkingItemSource, setLinkingItemSource] = useState<"review" | "non_human">("review");
  const [pageInput, setPageInput] = useState("1");
  const [singleSession, setSingleSession] = useState<SingleReviewSession | null>(null);
  const pendingSinglePageDirectionRef = useRef<{ direction: 1 | -1; targetSkip: number } | null>(null);

  // Non-human candidates now share the general V2 list through a filter.
  // Keep the legacy queue code unreachable until it can be removed independently.
  const [panelMode] = useState<"review" | "non_human">("review");
  const [nhItems, setNhItems] = useState<V2ReviewCharacter[]>([]);
  const [nhTotal, setNhTotal] = useState(0);
  const [nhSkip, setNhSkip] = useState(0);
  const [nhSearch, setNhSearch] = useState("");
  const [nhRatingStatus, setNhRatingStatus] = useState<NonHumanRatingFilter>("unrated");
  const [nhLoading, setNhLoading] = useState(false);
  const [nhError, setNhError] = useState<string | null>(null);
  const [nhActionMessage, setNhActionMessage] = useState<string | null>(null);
  const [nhRecalculating, setNhRecalculating] = useState(false);
  const [nhFocusIndex, setNhFocusIndex] = useState(0);
  const [nhActingIds, setNhActingIds] = useState<Set<number>>(() => new Set());
  const [nhFailedMessages, setNhFailedMessages] = useState<Record<number, string>>({});
  const [nhPreviewOpen, setNhPreviewOpen] = useState(false);
  const [nhPreviewFit, setNhPreviewFit] = useState(true);
  // Detail-overlay decisions are deliberately separate from the grid's immediate
  // quick-review actions. They survive local overlay navigation until batch apply.
  const [nhOverlayDecisions, setNhOverlayDecisions] = useState<Record<number, NonHumanOverlayDecision>>({});
  const [nhOverlayFailedMessages, setNhOverlayFailedMessages] = useState<Record<number, string>>({});
  const [nhOverlayBulkSaving, setNhOverlayBulkSaving] = useState(false);
  const nhItemsRef = useRef<V2ReviewCharacter[]>([]);
  const nhFocusIndexRef = useRef(0);

  const { v2Jobs: contextV2Jobs, startV2Regeneration } = useGenerationJobs();
  const processedV2JobIdsRef = useRef<Set<string>>(new Set());
  const v2JobsByCharacter = useMemo(() => {
    const next: Record<number, V2GenerationJobState> = {};
    for (const job of contextV2Jobs) {
      if (job.kind === "regenerate" && job.character_id != null) {
        next[job.character_id] = job;
      }
    }
    return next;
  }, [contextV2Jobs]);

  const itemsRef = useRef<V2ReviewCharacter[]>([]);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  useEffect(() => {
    focusIndexRef.current = focusIndex;
  }, [focusIndex]);

  useEffect(() => {
    nhItemsRef.current = nhItems;
  }, [nhItems]);

  useEffect(() => {
    nhFocusIndexRef.current = nhFocusIndex;
  }, [nhFocusIndex]);

  const isCharacterRegenerating = useCallback(
    (characterId: number) => {
      const job = v2JobsByCharacter[characterId];
      return Boolean(job && (job.status === "queued" || job.status === "running" || job.status === "paused"));
    },
    [v2JobsByCharacter],
  );
  const regenCheckRef = useRef(isCharacterRegenerating);
  useEffect(() => {
    regenCheckRef.current = isCharacterRegenerating;
  }, [isCharacterRegenerating]);

  useEffect(() => {
    void api.getSettings().then((settings) => {
      setThumbSize(settings.review_thumbnail_size);
      setCardSize(getV2ReviewCardSize() ?? (settings.v2_review_card_size as V2ReviewCardSize) ?? "medium");
      setCardWidthPx(getV2ReviewCardWidthPx() ?? settings.v2_review_card_width_px ?? 0);
    });
  }, []);

  useEffect(
    () =>
      onV2ReviewCardSettingsChanged(() => {
        setCardSize(getV2ReviewCardSize() ?? "medium");
        setCardWidthPx(getV2ReviewCardWidthPx() ?? 0);
      }),
    [],
  );

  const effectiveCardWidthPx = resolveV2ReviewCardWidthPx(cardSize, cardWidthPx);

  useEffect(() => {
    const node = scrollRef.current;
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
    // items.length: 그리드는 목록 로드 후에 렌더되므로, 첫 로드 시점에 ref가 채워진 뒤 다시 측정해야 한다.
  }, [effectiveCardWidthPx, items.length]);

  const loadStats = useCallback(async () => {
    try {
      const response = await api.getV2ReviewStats();
      setStats(response);
    } catch {
      // 진행 통계는 부가 정보이므로 실패해도 목록 조회에 영향을 주지 않는다.
    }
  }, []);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  const loadReviews = useCallback(async (preferredFocusId?: number) => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listV2ReviewCharacters({
        review_status: reviewStatus || undefined,
        rating: ratingFilter || undefined,
        quality_status: qualityStatus || undefined,
        identity_status: identityStatus || undefined,
        generation_status: generationStatus || undefined,
        gender: genderFilter || undefined,
        non_human: nonHumanFilter === "all" ? undefined : nonHumanFilter,
        series_id: seriesId || undefined,
        multicolor: multicolorFilter || undefined,
        prompt_modified: promptModifiedOnly ? true : undefined,
        search: search || undefined,
        skip,
        limit: PAGE_SIZE,
      });
      loadedSkipRef.current = skip;
      // 재생성 진행 중인 항목이 목록 응답에서 일시적으로 빠질 수 있으므로, 재생성이
      // 끝날 때까지 기존 위치에 유지한다.
      const fetchedIds = new Set(response.items.map((item) => item.id));
      const kept = itemsRef.current
        .map((item, index) => ({ item, index }))
        .filter(({ item }) => !fetchedIds.has(item.id) && regenCheckRef.current(item.id));
      const merged = [...response.items];
      for (const { item, index } of kept) {
        merged.splice(Math.min(index, merged.length), 0, item);
      }
      setItems(merged);
      setTotal(response.total);
      const currentFocusId = itemsRef.current[focusIndexRef.current]?.id;
      const targetFocusId = preferredFocusId ?? currentFocusId;
      setFocusIndex((current) => {
        if (targetFocusId != null) {
          const matchingIndex = merged.findIndex((entry) => entry.id === targetFocusId);
          if (matchingIndex >= 0) {
            return matchingIndex;
          }
        }
        return Math.min(current, Math.max(0, merged.length - 1));
      });
      setDrafts((current) =>
        Object.fromEntries(merged.map((item) => [item.id, current[item.id] ?? createV2DraftForItem(item)])),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "V2 리뷰 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [
    reviewStatus,
    ratingFilter,
    qualityStatus,
    identityStatus,
    generationStatus,
    genderFilter,
    nonHumanFilter,
    seriesId,
    multicolorFilter,
    promptModifiedOnly,
    search,
    skip,
  ]);

  useEffect(() => {
    void loadReviews();
  }, [loadReviews]);

  const loadNonHumanQueue = useCallback(
    async (preferredFocusId?: number) => {
      setNhLoading(true);
      setNhError(null);
      try {
        const response = await api.listNonHumanCandidates({
          filter_status: "pending",
          rating_filter: nhRatingStatus,
          search: nhSearch || undefined,
          skip: nhSkip,
          limit: PAGE_SIZE,
        });
        setNhItems(response.items);
        setNhTotal(response.total);
        const currentFocusId = nhItemsRef.current[nhFocusIndexRef.current]?.id;
        const targetFocusId = preferredFocusId ?? currentFocusId;
        const matchingIndex =
          targetFocusId != null ? response.items.findIndex((entry) => entry.id === targetFocusId) : -1;
        setNhFocusIndex(matchingIndex >= 0 ? matchingIndex : 0);
      } catch (err) {
        setNhError(err instanceof Error ? err.message : "비인간 후보 큐를 불러오지 못했습니다.");
      } finally {
        setNhLoading(false);
      }
    },
    [nhRatingStatus, nhSearch, nhSkip],
  );

  useEffect(() => {
    if (panelMode !== "non_human") {
      return;
    }
    void loadNonHumanQueue();
  }, [panelMode, loadNonHumanQueue]);

  useEffect(() => {
    setNhSkip(0);
  }, [nhRatingStatus, nhSearch]);

  const nhAdvance = useCallback(
    (characterId: number) => {
      const currentIndex = nhItemsRef.current.findIndex((entry) => entry.id === characterId);
      const nextItems = nhItemsRef.current.filter((entry) => entry.id !== characterId);
      setNhItems(nextItems);
      setNhTotal((current) => Math.max(0, current - 1));
      setNhFocusIndex(Math.min(currentIndex >= 0 ? currentIndex : 0, Math.max(0, nextItems.length - 1)));
      void loadNonHumanQueue();
    },
    [loadNonHumanQueue],
  );

  const nhConfirm = useCallback(
    async (item: V2ReviewCharacter, rating: -1 | 3) => {
      setNhActingIds((current) => new Set(current).add(item.id));
      setNhError(null);
      setNhFailedMessages((current) => {
        if (!(item.id in current)) return current;
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      try {
        await api.confirmNonHumanCandidate(item.id, { rating });
        setNhActionMessage(`${item.character_tag} 확정 (rating ${rating}) · 다음 항목으로 이동`);
        nhAdvance(item.id);
      } catch (err) {
        const message = err instanceof Error ? err.message : "확정에 실패했습니다.";
        setNhError(message);
        setNhFailedMessages((current) => ({ ...current, [item.id]: message }));
      } finally {
        setNhActingIds((current) => {
          const next = new Set(current);
          next.delete(item.id);
          return next;
        });
      }
    },
    [nhAdvance],
  );

  const nhExclude = useCallback(
    async (item: V2ReviewCharacter) => {
      setNhActingIds((current) => new Set(current).add(item.id));
      setNhError(null);
      setNhFailedMessages((current) => {
        if (!(item.id in current)) return current;
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      try {
        await api.excludeNonHumanCandidate(item.id);
        setNhActionMessage(`${item.character_tag} 제외 · 다음 항목으로 이동`);
        nhAdvance(item.id);
      } catch (err) {
        const message = err instanceof Error ? err.message : "제외에 실패했습니다.";
        setNhError(message);
        setNhFailedMessages((current) => ({ ...current, [item.id]: message }));
      } finally {
        setNhActingIds((current) => {
          const next = new Set(current);
          next.delete(item.id);
          return next;
        });
      }
    },
    [nhAdvance],
  );

  const recalculateNonHumanCandidates = useCallback(async () => {
    setNhRecalculating(true);
    setNhError(null);
    try {
      const summary = await api.recalculateNonHumanCandidates();
      setNhActionMessage(
        `후보 재계산 완료 · ${summary.updated.toLocaleString()}개 갱신 / ${summary.scanned.toLocaleString()}개 검사 / 후보 ${summary.candidate_count.toLocaleString()}개 / 결정 보존 ${summary.skipped_decided.toLocaleString()}개`,
      );
      await loadNonHumanQueue();
    } catch (err) {
      setNhError(err instanceof Error ? err.message : "비인간 후보 재계산에 실패했습니다.");
    } finally {
      setNhRecalculating(false);
    }
  }, [loadNonHumanQueue]);

  const nhFocusedItem = nhItems[nhFocusIndex] ?? null;
  const nhFocusedActing = nhFocusedItem ? nhActingIds.has(nhFocusedItem.id) : false;
  const nhFocusedImage = nhFocusedItem?.preview_image ?? null;
  const nhPreviewSrc = nhFocusedImage ? pendingReviewImageUrl(nhFocusedImage.image_path) : null;
  const nhPreviewAlt = nhFocusedItem ? `${nhFocusedItem.character_tag} preview` : "";

  // Keeps the window-level s/S handler bound to the selected queue item.
  const openNonHumanDetails = useCallback((item: V2ReviewCharacter) => {
    setSingleSession((current) =>
      current?.source === "non_human" && current.itemId === item.id
        ? current
        : { source: "non_human", itemId: item.id },
    );
  }, []);

  // singleSession pins the overlay to one (source, itemId) pair so it never rebinds to
  // whichever tab/card happens to be live-focused - see corrective patch for the
  // General Review <-> non-human queue overlay mismatch bug.
  const singleModeIsNonHuman = singleSession?.source === "non_human";
  const singleSessionList = singleModeIsNonHuman ? nhItems : items;
  const singleSessionItem = singleSession
    ? singleSessionList.find((entry) => entry.id === singleSession.itemId) ?? null
    : null;
  const singleModeOpen = singleSessionItem !== null;
  const singleSessionRowIndex = singleSession
    ? singleSessionList.findIndex((entry) => entry.id === singleSession.itemId)
    : -1;
  const singleModeItem = singleSessionItem;
  const singleModeDraft = singleSessionItem
    ? drafts[singleSessionItem.id] ?? createV2DraftForItem(singleSessionItem)
    : null;
  const singleModeRowIndex = singleSessionRowIndex;
  const singleModeNonHumanDecision =
    singleModeIsNonHuman && singleSessionItem ? nhOverlayDecisions[singleSessionItem.id] : undefined;
  const singleModeGlobalIndex = singleSession
    ? (singleModeIsNonHuman ? nhSkip : skip) + Math.max(0, singleSessionRowIndex)
    : 0;
  const singleModeTotal = singleModeIsNonHuman ? nhTotal : total;
  const singleModeLocked = singleModeIsNonHuman
    ? nhOverlayBulkSaving || (singleSessionItem ? isCharacterRegenerating(singleSessionItem.id) : false)
    : singleSessionItem
      ? submittingId === singleSessionItem.id ||
        isCharacterRegenerating(singleSessionItem.id) ||
        savingIds.has(singleSessionItem.id)
      : false;

  const singleModeDisplayDraft = singleModeDraft;

  const closeSingleSession = useCallback(() => {
    if (singleSessionRowIndex >= 0) {
      if (singleSession?.source === "review") {
        focusCardFromKeyboardRef.current = true;
        setFocusIndex(singleSessionRowIndex);
      } else if (singleSession?.source === "non_human") {
        setNhFocusIndex(singleSessionRowIndex);
      }
    }
    setSingleSession(null);
  }, [singleSession, singleSessionRowIndex]);

  useEffect(() => {
    if (!singleSession || singleSession.source !== "review") {
      return;
    }
    if (loading || pendingSinglePageDirectionRef.current) {
      return;
    }
    if (!items.some((entry) => entry.id === singleSession.itemId)) {
      setSingleSession(null);
    }
  }, [items, loading, singleSession]);

  useEffect(() => {
    if (!singleSession || singleSession.source !== "non_human") {
      return;
    }
    if (nhLoading) {
      return;
    }
    if (!nhItems.some((entry) => entry.id === singleSession.itemId)) {
      setSingleSession(null);
    }
  }, [nhItems, nhLoading, singleSession]);

  const nhNavigateSingleLocal = useCallback(
    (direction: 1 | -1) => {
      const current = singleSession?.source === "non_human" ? singleSessionRowIndex : nhFocusIndex;
      const next = current + direction;
      if (next < 0 || next >= nhItems.length) {
        return false;
      }
      setNhFocusIndex(next);
      const nextItem = nhItems[next];
      if (nextItem) {
        setSingleSession({ source: "non_human", itemId: nextItem.id });
      }
      return true;
    },
    [singleSession, singleSessionRowIndex, nhFocusIndex, nhItems],
  );

  // Shared by the grid's focused-card shortcut and the single-item overlay so both
  // "accept suggested rating" entry points run the exact same validation/confirm call.
  const nhConfirmProposedFor = useCallback(
    (item: V2ReviewCharacter) => {
      if (nhActingIds.has(item.id)) {
        return;
      }
      const suggested = item.non_human_suggested_rating;
      if (suggested !== -1 && suggested !== 3) {
        setNhActionMessage("제안된 레이팅이 없습니다. -1 또는 3을 직접 선택하세요.");
        return;
      }
      void nhConfirm(item, suggested);
    },
    [nhActingIds, nhConfirm],
  );

  const nhConfirmProposed = useCallback(() => {
    if (!nhFocusedItem) {
      return;
    }
    nhConfirmProposedFor(nhFocusedItem);
  }, [nhFocusedItem, nhConfirmProposedFor]);

  // The only non-human-specific staged action left: 'e' has no draft equivalent,
  // so exclusion still needs an explicit flag distinct from the shared draft.
  const stageNonHumanOverlayExclude = useCallback((item: V2ReviewCharacter) => {
    setNhOverlayDecisions((current) => ({ ...current, [item.id]: { action: "exclude" } }));
    setNhOverlayFailedMessages((current) => {
      if (!(item.id in current)) return current;
      const next = { ...current };
      delete next[item.id];
      return next;
    });
    setNhActionMessage(`${item.character_tag} 제외를 임시 저장했습니다. Ctrl+Enter로 적용하세요.`);
  }, []);

  // Rating keys write straight into the shared draft (parity with General), but must
  // also clear any staged exclude - pressing a rating after 'e' cancels/replaces it.
  const setNonHumanOverlayRating = useCallback(
    (item: V2ReviewCharacter, value: number) => {
      const current = drafts[item.id] ?? createV2DraftForItem(item);
      updateDraft(item.id, { ...current, rating: toggleRating(current.rating, value) });
      setNhOverlayDecisions((currentDecisions) => {
        if (currentDecisions[item.id]?.action !== "exclude") return currentDecisions;
        const next = { ...currentDecisions };
        delete next[item.id];
        return next;
      });
      setNhOverlayFailedMessages((current) => {
        if (!(item.id in current)) return current;
        const next = { ...current };
        delete next[item.id];
        return next;
      });
    },
    [drafts],
  );

  type NonHumanPlanItem =
    | { kind: "exclude"; item: V2ReviewCharacter }
    | { kind: "confirm"; item: V2ReviewCharacter; draft: V2CharacterDraft };

  // A staged exclude always wins (it has no draft representation to compare against).
  // Otherwise a change only counts if the draft actually differs from the item's saved
  // state. The non-human "confirm" bulk action accepts any V2 rating (-1..6) plus the
  // full draft payload, so every rated draft goes through it and marks the candidate
  // decision atomically. Like General Review bulk-save, unrated edits remain staged.
  const buildNonHumanPlan = useCallback(
    (pool: V2ReviewCharacter[]): NonHumanPlanItem[] => {
      const planned: NonHumanPlanItem[] = [];
      for (const item of pool) {
        if (nhOverlayDecisions[item.id]?.action === "exclude") {
          planned.push({ kind: "exclude", item });
          continue;
        }
        const draft = drafts[item.id];
        if (!draft || !isDraftChanged(item, draft) || draft.rating === null) {
          continue;
        }
        planned.push({ kind: "confirm", item, draft });
      }
      return planned;
    },
    [nhOverlayDecisions, drafts],
  );

  // "confirm" carries the complete editable payload (rating/cover image/gender/prompt/
  // tags) in a single bulk-apply request - the backend applies both the candidate
  // decision and the V2 save atomically (see NonHumanReviewService.confirm). "exclude"
  // is status-only; unrated draft edits are deliberately not part of this plan.
  const runNonHumanPlan = useCallback(async (planned: NonHumanPlanItem[]) => {
    const appliedIds = new Set<number>();
    const failedById: Record<number, string> = {};

    const bulkItems = planned.map((entry) => {
      if (entry.kind === "exclude") {
        return { character_id: entry.item.id, action: "exclude" as const };
      }
      const chips = v2AppearanceTagChips(entry.item);
      const enabledTags = entry.draft.enabledTags.size > 0 ? entry.draft.enabledTags : defaultEnabledTagKeys(chips);
      const selectedImage = entry.item.images[entry.draft.imageIndex];
      return {
        character_id: entry.item.id,
        action: "confirm" as const,
        rating: entry.draft.rating as number,
        cover_image_id: selectedImage ? selectedImage.id : null,
        gender: entry.draft.gender,
        base_prompt: resolveV2FinalPrompt(entry.item, { ...entry.draft, enabledTags }),
        selected_tags: v2SelectedTagsPayload(entry.item, enabledTags),
      };
    });

    if (bulkItems.length > 0) {
      try {
        const response = await api.bulkApplyNonHumanCandidates({ items: bulkItems });
        for (const result of response.results) {
          if (result.status === "applied") {
            appliedIds.add(result.character_id);
          } else {
            failedById[result.character_id] = result.error || "적용에 실패했습니다.";
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "임시 변경사항 적용에 실패했습니다.";
        for (const bulkItem of bulkItems) {
          failedById[bulkItem.character_id] = message;
        }
      }
    }

    return { appliedIds, failedById };
  }, []);

  // Ctrl+Enter: batch-applies every staged change across the whole non-human queue
  // (not just the open item) - matches the existing "batch persistence" behavior.
  const applyNonHumanOverlayDecisions = useCallback(async () => {
    if (nhOverlayBulkSaving) {
      return;
    }
    const planned = buildNonHumanPlan(nhItems);
    if (planned.length === 0) {
      const hasUnratedDraft = nhItems.some((item) => {
        const draft = drafts[item.id];
        return draft && isDraftChanged(item, draft) && draft.rating === null && !nhOverlayDecisions[item.id];
      });
      setNhActionMessage(
        hasUnratedDraft
          ? "레이팅이 없는 편집 내용은 임시 상태로 유지됩니다. 저장하려면 레이팅을 선택하세요."
          : "적용할 임시 변경사항이 없습니다.",
      );
      return;
    }

    setNhOverlayBulkSaving(true);
    setNhError(null);
    try {
      const { appliedIds, failedById } = await runNonHumanPlan(planned);

      setNhOverlayDecisions((current) =>
        Object.fromEntries(Object.entries(current).filter(([characterId]) => !appliedIds.has(Number(characterId)))),
      );
      setNhOverlayFailedMessages(failedById);
      setDrafts((current) => {
        const next = { ...current };
        for (const id of appliedIds) {
          delete next[id];
        }
        return next;
      });

      const currentId = singleSession?.source === "non_human" ? singleSession.itemId : null;
      const currentIndex = currentId == null ? -1 : nhItems.findIndex((item) => item.id === currentId);
      const remainingItems = nhItems.filter((item) => !appliedIds.has(item.id));
      const preferredItem =
        currentId != null && appliedIds.has(currentId)
          ? remainingItems[currentIndex] ?? remainingItems[Math.max(0, currentIndex - 1)] ?? null
          : remainingItems.find((item) => item.id === currentId) ?? remainingItems[0] ?? null;

      setNhItems(remainingItems);
      setNhTotal((current) => Math.max(0, current - appliedIds.size));
      if (preferredItem) {
        setNhFocusIndex(Math.max(0, remainingItems.findIndex((item) => item.id === preferredItem.id)));
        setSingleSession((current) =>
          current?.source === "non_human" ? { source: "non_human", itemId: preferredItem.id } : current,
        );
      } else if (currentId != null && appliedIds.has(currentId)) {
        setSingleSession(null);
      }

      const failedCount = Object.keys(failedById).length;
      setNhActionMessage(
        failedCount > 0
          ? `${appliedIds.size}개 적용, ${failedCount}개 실패했습니다. 실패 항목은 임시 변경으로 유지됩니다.`
          : `${appliedIds.size}개 변경사항을 적용했습니다.`,
      );
      await loadNonHumanQueue(preferredItem?.id);
    } catch (err) {
      const message = err instanceof Error ? err.message : "임시 변경사항 적용에 실패했습니다.";
      setNhError(message);
    } finally {
      setNhOverlayBulkSaving(false);
    }
  }, [
    buildNonHumanPlan,
    drafts,
    loadNonHumanQueue,
    nhItems,
    nhOverlayBulkSaving,
    nhOverlayDecisions,
    runNonHumanPlan,
    singleSession,
  ]);

  // Bare Enter in the overlay: persists just the open item now (parity with General's
  // single-item complete), instead of waiting for a Ctrl+Enter batch apply.
  const completeNonHumanSingleItem = useCallback(
    async (item: V2ReviewCharacter) => {
      if (nhOverlayBulkSaving) {
        return;
      }
      const planned = buildNonHumanPlan([item]);
      if (planned.length === 0) {
        const draft = drafts[item.id];
        setNhActionMessage(
          draft && isDraftChanged(item, draft) && draft.rating === null
            ? "레이팅을 선택해야 현재 편집 내용을 저장할 수 있습니다."
            : "변경된 내용이 없습니다.",
        );
        return;
      }
      setNhOverlayBulkSaving(true);
      setNhError(null);
      try {
        const { appliedIds, failedById } = await runNonHumanPlan(planned);
        if (appliedIds.has(item.id)) {
          setNhOverlayDecisions((current) => {
            if (!(item.id in current)) return current;
            const next = { ...current };
            delete next[item.id];
            return next;
          });
          setNhOverlayFailedMessages((current) => {
            if (!(item.id in current)) return current;
            const next = { ...current };
            delete next[item.id];
            return next;
          });
          forgetDraft(item.id);
          setNhActionMessage(`${item.character_tag} 저장 완료 · 다음 항목으로 이동`);
          nhAdvance(item.id);
        } else {
          const message = failedById[item.id] || "저장에 실패했습니다.";
          setNhOverlayFailedMessages((current) => ({ ...current, [item.id]: message }));
          setNhError(message);
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "저장에 실패했습니다.";
        setNhError(message);
        setNhOverlayFailedMessages((current) => ({ ...current, [item.id]: message }));
      } finally {
        setNhOverlayBulkSaving(false);
      }
    },
    [buildNonHumanPlan, drafts, nhAdvance, nhOverlayBulkSaving, runNonHumanPlan],
  );

  useEffect(() => {
    if (!nhFocusedItem || !nhPreviewSrc) {
      setNhPreviewOpen(false);
    }
  }, [nhFocusedItem, nhPreviewSrc]);

  useEffect(() => {
    if (nhFocusedActing) {
      setNhPreviewOpen(false);
    }
  }, [nhFocusedActing]);

  const nhTogglePreview = useCallback(() => {
    if (nhFocusedActing) {
      return;
    }
    setNhPreviewOpen((open) => {
      if (open) {
        return false;
      }
      if (nhPreviewSrc) {
        setNhPreviewFit(true);
        return true;
      }
      return false;
    });
  }, [nhFocusedActing, nhPreviewSrc]);

  // Keeps the selected non-human card's row top aligned with the grid viewport top
  // (within ~4px) and, on keyboard-driven selection, moves DOM focus onto it - mirrors
  // the General Review scroll/focus effect but scoped to panelMode and its own ref so
  // clicks/filter resets don't steal focus.
  useEffect(() => {
    if (panelMode !== "non_human") {
      return;
    }
    const node = scrollRef.current;
    const item = nhItems[nhFocusIndex];
    if (!node || !item) {
      return;
    }
    const row = node.querySelector(`[data-character-id="${item.id}"]`);
    const shouldFocusCard = nhFocusCardFromKeyboardRef.current;
    nhFocusCardFromKeyboardRef.current = false;
    if (!(row instanceof HTMLElement)) {
      return;
    }
    const containerTop = node.getBoundingClientRect().top;
    const rowTop = row.getBoundingClientRect().top;
    const delta = rowTop - containerTop;
    if (Math.abs(delta) > 4) {
      node.scrollTop += delta;
    }
    if (shouldFocusCard && !isEditableTarget(document.activeElement)) {
      row.focus({ preventScroll: true });
    }
  }, [panelMode, nhFocusIndex, nhItems]);

  useEffect(() => {
    if (panelMode !== "non_human") {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target) || !nhFocusedItem || nhLoading || singleModeOpen) {
        return;
      }
      const key = event.key.toLowerCase();

      if (nhFocusedActing) {
        const allowed = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key) || key === "q" || key === "w";
        if (!allowed) {
          event.preventDefault();
        }
        return;
      }

      if (key === "s" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        openNonHumanDetails(nhFocusedItem);
        return;
      }

      if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        nhTogglePreview();
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setNhFocusIndex((index) => {
          const next = Math.max(0, index - 1);
          nhFocusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        setNhFocusIndex((index) => {
          const next = Math.min(nhItems.length - 1, index + 1);
          nhFocusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setNhFocusIndex((index) => {
          const next = Math.max(0, index - 5);
          nhFocusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setNhFocusIndex((index) => {
          const next = Math.min(nhItems.length - 1, index + 5);
          nhFocusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        nhConfirmProposed();
        return;
      }
      if (event.key === "3") {
        event.preventDefault();
        void nhConfirm(nhFocusedItem, 3);
        return;
      }
      if (event.key === "-" || (key === "x" && !event.ctrlKey && !event.metaKey && !event.altKey)) {
        event.preventDefault();
        void nhConfirm(nhFocusedItem, -1);
        return;
      }
      if (key === "e" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        void nhExclude(nhFocusedItem);
        return;
      }
      if (key === "q") {
        event.preventDefault();
        window.open(
          `https://danbooru.donmai.us/posts?tags=${encodeURIComponent(`${nhFocusedItem.character_tag} solo`.trim())}`,
          "_blank",
          "noopener,noreferrer",
        );
        return;
      }
      if (key === "w") {
        event.preventDefault();
        window.open(
          nhFocusedItem.danbooru_wiki_url ||
            `https://danbooru.donmai.us/wiki_pages/${encodeURIComponent(nhFocusedItem.character_tag)}`,
          "_blank",
          "noopener,noreferrer",
        );
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [
    panelMode,
    nhFocusedItem,
    nhFocusedActing,
    nhLoading,
    nhItems.length,
    singleModeOpen,
    nhConfirmProposed,
    nhConfirm,
    nhExclude,
    nhTogglePreview,
    openNonHumanDetails,
  ]);

  useEffect(() => {
    const pendingNavigation = pendingSinglePageDirectionRef.current;
    if (
      !pendingNavigation ||
      loading ||
      loadedSkipRef.current !== pendingNavigation.targetSkip ||
      skip !== pendingNavigation.targetSkip
    ) {
      return;
    }
    pendingSinglePageDirectionRef.current = null;
    const nextIndex =
      pendingNavigation.direction > 0
        ? items.findIndex((entry) => entry.review_status === "pending")
        : items.map((entry) => entry.review_status).lastIndexOf("pending");
    if (nextIndex >= 0) {
      focusCardFromKeyboardRef.current = true;
      setFocusIndex(nextIndex);
      setSingleSession({ source: "review", itemId: items[nextIndex].id });
      return;
    }
    setActionMessage("이동할 pending 항목이 없습니다.");
  }, [items, loading, skip]);

  useEffect(() => {
    setSkip(0);
    setFocusIndex(0);
    setSingleSession((current) => (current?.source === "review" ? null : current));
  }, [
    reviewStatus,
    ratingFilter,
    qualityStatus,
    identityStatus,
    generationStatus,
    genderFilter,
    nonHumanFilter,
    seriesId,
    multicolorFilter,
    promptModifiedOnly,
    search,
  ]);

  const addToSet = (values: Set<number>, id: number) => {
    const next = new Set(values);
    next.add(id);
    return next;
  };

  const removeFromSet = (values: Set<number>, id: number) => {
    const next = new Set(values);
    next.delete(id);
    return next;
  };

  const removeManyFromSet = (values: Set<number>, ids: Set<number>) => {
    const next = new Set(values);
    for (const id of ids) {
      next.delete(id);
    }
    return next;
  };

  const clearFailedMessage = (characterId: number) => {
    setFailedMessages((current) => {
      if (!(characterId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[characterId];
      return next;
    });
  };

  const forgetDraft = (characterId: number) => {
    setDrafts((current) => {
      if (!(characterId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[characterId];
      return next;
    });
  };

  const updateDraft = (characterId: number, draft: V2CharacterDraft) => {
    setDrafts((current) => ({ ...current, [characterId]: draft }));
    const item = [...itemsRef.current, ...nhItemsRef.current].find((entry) => entry.id === characterId);
    setDirtyIds((current) =>
      item && !isDraftChanged(item, draft) ? removeFromSet(current, characterId) : addToSet(current, characterId),
    );
    clearFailedMessage(characterId);
  };

  // Takes the full item (not just its id) because it also serves the non-human
  // overlay, whose items live in nhItems rather than the general `items` list -
  // an id-only lookup against `items` silently no-oped for those.
  const toggleTag = (item: V2ReviewCharacter, tagKey: string) => {
    const current = drafts[item.id] ?? createV2DraftForItem(item);
    const chips = v2AppearanceTagChips(item);
    const enabled = new Set(current.enabledTags.size > 0 ? current.enabledTags : defaultEnabledTagKeys(chips));
    if (enabled.has(tagKey)) {
      enabled.delete(tagKey);
    } else {
      if (tagKey.startsWith("hair:") && !hasMulticolorHairTag(enabled)) {
        for (const key of Array.from(enabled)) {
          if (key.startsWith("hair:")) {
            enabled.delete(key);
          }
        }
      }
      enabled.add(tagKey);
    }
    const nextEnabled = normalizeHairTags(enabled);
    updateDraft(item.id, { ...current, enabledTags: nextEnabled });
  };

  const setRating = (characterId: number, value: number) => {
    const item = [...items, ...nhItems].find((entry) => entry.id === characterId);
    if (!item) return;
    const current = drafts[characterId] ?? createV2DraftForItem(item);
    updateDraft(characterId, { ...current, rating: toggleRating(current.rating, value) });
    if (value === 4) {
      setActionMessage("레이팅 4는 V2 1차 검수에서 비권장입니다. 다시 4를 눌러 해제하거나 1/2/3/5/6으로 수정할 수 있습니다.");
    }
  };

  const completeItem = async (item: V2ReviewCharacter) => {
    const draft = drafts[item.id] ?? createV2DraftForItem(item);
    const isRatingZero = draft.rating === 0 || draft.rating === -1;
    const image = item.images[draft.imageIndex];
    if (!isRatingZero && !image) {
      setActionMessage("선택할 이미지가 없습니다.");
      return;
    }
    const chips = v2AppearanceTagChips(item);
    const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
    const finalPrompt = resolveV2FinalPrompt(item, { ...draft, enabledTags });
    const completedIndex = itemsRef.current.findIndex((entry) => entry.id === item.id);

    setSubmittingId(item.id);
    setSavingIds((current) => addToSet(current, item.id));
    clearFailedMessage(item.id);
    setError(null);
    try {
      await api.completeV2ReviewCharacter(item.id, {
        cover_image_id: isRatingZero ? null : image!.id,
        gender: draft.gender,
        rating: draft.rating,
        base_prompt: finalPrompt,
        selected_tags: isRatingZero ? null : v2SelectedTagsPayload(item, enabledTags),
      });
      setActionMessage(`${item.character_tag} 리뷰 완료`);
      setDirtyIds((current) => removeFromSet(current, item.id));
      clearFailedMessage(item.id);
      forgetDraft(item.id);
      const nextItems = itemsRef.current.filter((entry) => entry.id !== item.id);
      setItems(nextItems);
      setTotal((current) => Math.max(0, current - 1));
      focusCardFromKeyboardRef.current = true;
      setFocusIndex(Math.min(completedIndex >= 0 ? completedIndex : focusIndex, Math.max(0, nextItems.length - 1)));
      await loadReviews();
      await loadStats();
    } catch (err) {
      const message = err instanceof Error ? err.message : "리뷰 완료에 실패했습니다.";
      setError(message);
      setFailedMessages((current) => ({ ...current, [item.id]: message }));
      setDirtyIds((current) => addToSet(current, item.id));
    } finally {
      setSubmittingId(null);
      setSavingIds((current) => removeFromSet(current, item.id));
    }
  };

  const bulkSaveRatedItems = useCallback(async () => {
    if (bulkSaving) {
      return;
    }
    const eligible = items.filter((item) => {
      if (isCharacterRegenerating(item.id)) return false;
      const draft = drafts[item.id];
      const rating = draft ? draft.rating : item.rating;
      return rating !== null && rating !== undefined;
    });
    if (eligible.length === 0) {
      setActionMessage("일괄 저장할 레이팅된 항목이 없습니다.");
      return;
    }

    setBulkSaving(true);
    const eligibleIds = new Set(eligible.map((item) => item.id));
    setSavingIds((current) => {
      const next = new Set(current);
      for (const id of eligibleIds) {
        next.add(id);
      }
      return next;
    });
    setFailedMessages((current) => {
      const next = { ...current };
      for (const id of eligibleIds) {
        delete next[id];
      }
      return next;
    });
    setError(null);
    try {
      const payloadItems = eligible.map((item) => {
        const draft = drafts[item.id] ?? createV2DraftForItem(item);
        const rating = draft.rating;
        const chips = v2AppearanceTagChips(item);
        const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
        const finalPrompt = resolveV2FinalPrompt(item, { ...draft, enabledTags });
        const selectedImage = item.images[draft.imageIndex];
        const coverImageId = selectedImage ? selectedImage.id : undefined;
        return {
          character_id: item.id,
          rating,
          gender: draft.gender,
          base_prompt: finalPrompt,
          selected_tags: v2SelectedTagsPayload(item, enabledTags),
          cover_image_id: coverImageId,
        };
      });
      const response = await api.bulkCompleteV2ReviewCharacters({ items: payloadItems });
      const failedTags = response.results
        .filter((result) => result.status === "failed")
        .map((result) => {
          const failedItem = items.find((entry) => entry.id === result.character_id);
          return failedItem ? failedItem.character_tag : `#${result.character_id}`;
        });
      const failedResults = response.results.filter((result) => result.status === "failed");
      const failedIds = new Set(failedResults.map((result) => result.character_id));
      const succeededIds = new Set(
        response.results.filter((result) => result.status === "completed").map((result) => result.character_id),
      );
      setActionMessage(`완료 ${response.completed} · 건너뜀 ${response.skipped} · 실패 ${response.failed}`);
      if (failedTags.length > 0) {
        setError(`일괄 저장 실패: ${failedTags.join(", ")}`);
        setFailedMessages((current) => {
          const next = { ...current };
          for (const result of failedResults) {
            const failedItem = items.find((entry) => entry.id === result.character_id);
            next[result.character_id] = result.error || `${failedItem?.character_tag ?? result.character_id} 저장 실패`;
          }
          return next;
        });
        const firstFailedIndex = items.findIndex((entry) => failedIds.has(entry.id));
        if (firstFailedIndex >= 0) {
          focusCardFromKeyboardRef.current = true;
          setFocusIndex(firstFailedIndex);
        }
      }
      setDirtyIds((current) => removeManyFromSet(current, succeededIds));
      for (const id of succeededIds) {
        clearFailedMessage(id);
        forgetDraft(id);
      }
      if (failedTags.length === 0) {
        setFocusIndex(0);
        scrollRef.current?.scrollTo({ top: 0 });
      }
      if (singleModeOpen) {
        await loadReviews();
      } else if (skip !== 0) {
        setSkip(0);
      } else {
        await loadReviews();
      }
      await loadStats();
    } catch (err) {
      const message = err instanceof Error ? err.message : "일괄 저장에 실패했습니다.";
      setError(message);
      setFailedMessages((current) => {
        const next = { ...current };
        for (const item of eligible) {
          next[item.id] = message;
        }
        return next;
      });
    } finally {
      setBulkSaving(false);
      setSavingIds((current) => removeManyFromSet(current, eligibleIds));
    }
  }, [bulkSaving, items, drafts, isCharacterRegenerating, skip, loadReviews, loadStats, singleModeOpen]);

  const reviewListFilters = useMemo<V2ReviewFilters>(
    () => ({
      review_status: reviewStatus || undefined,
      rating: ratingFilter || undefined,
      quality_status: qualityStatus || undefined,
      identity_status: identityStatus || undefined,
      generation_status: generationStatus || undefined,
      gender: genderFilter || undefined,
      non_human: nonHumanFilter === "all" ? undefined : nonHumanFilter,
      series_id: seriesId || undefined,
      multicolor: multicolorFilter || undefined,
      prompt_modified: promptModifiedOnly ? true : undefined,
      search: search || undefined,
    }),
    [
      reviewStatus,
      ratingFilter,
      qualityStatus,
      identityStatus,
      generationStatus,
      genderFilter,
      nonHumanFilter,
      seriesId,
      multicolorFilter,
      promptModifiedOnly,
      search,
    ],
  );

  const navigateSingleLocal = useCallback(
    (direction: 1 | -1) => {
      const current = singleSession?.source === "review" ? singleSessionRowIndex : focusIndex;
      const start = current + direction;
      for (let index = start; index >= 0 && index < items.length; index += direction) {
        if (items[index]?.review_status === "pending") {
          focusCardFromKeyboardRef.current = true;
          setFocusIndex(index);
          setSingleSession({ source: "review", itemId: items[index].id });
          return true;
        }
      }
      return false;
    },
    [singleSession, singleSessionRowIndex, focusIndex, items],
  );

  const navigateSinglePage = useCallback(
    (direction: 1 | -1) => {
      const nextSkip = skip + direction * PAGE_SIZE;
      if (nextSkip < 0 || nextSkip >= total) {
        setActionMessage("이동할 pending 페이지가 없습니다.");
        return;
      }
      pendingSinglePageDirectionRef.current = { direction, targetSkip: nextSkip };
      setSkip(nextSkip);
    },
    [skip, total],
  );

  const fetchPurgePreview = useCallback(
    () => api.previewPurgeUnselectedCatalogImagesGlobal({ search: search.trim() || undefined }),
    [search],
  );

  const submitPurgeSelected = useCallback(
    (characterIds: number[]) => api.purgeUnselectedCatalogImagesSelectedGlobal({ character_ids: characterIds }),
    [],
  );

  const handlePurgeCompleted = useCallback(
    (result: { affected_count: number; removed_count: number }) => {
      setActionMessage(
        `${result.affected_count}개 항목에서 미선택 이미지 ${result.removed_count}개를 삭제했습니다.`,
      );
      void loadReviews();
      void loadStats();
    },
    [loadReviews, loadStats],
  );

  // V2 응답(quality/identity 상태, image_id 등)으로 해당 카드 하나만 다시 조회해 직접 갱신한다.
  // V1 job의 CatalogReviewItem 변환을 거치지 않는다.
  const refreshSingleCharacter = useCallback(
    async (characterId: number, characterTag: string) => {
      try {
        const response = await api.listV2ReviewCharacters({ search: characterTag, skip: 0, limit: 10 });
        const updated =
          response.items.find((entry) => entry.id === characterId) ??
          response.items.find((entry) => entry.character_tag === characterTag);
        if (!updated) {
          await loadReviews();
          return;
        }
        setItems((current) => current.map((entry) => (entry.id === characterId ? updated : entry)));
        setDrafts((current) => ({ ...current, [characterId]: createV2DraftForItem(updated) }));
      } catch {
        await loadReviews();
      }
    },
    [loadReviews],
  );

  const onV2JobSettled = useCallback(
    async (job: V2GenerationJobState) => {
      if (processedV2JobIdsRef.current.has(job.job_id)) {
        return;
      }
      processedV2JobIdsRef.current.add(job.job_id);
      if (job.status === "failed") {
        setError(job.last_failure_reason || job.message || `${job.current_character_tag} 재생성 실패`);
        return;
      }
      if (job.status !== "completed") {
        return;
      }
      setActionMessage(
        `${job.current_character_tag} 재생성 완료 (품질: ${job.quality_status ?? "-"} · 재현: ${job.identity_status ?? "-"})`,
      );
      if (job.character_id != null) {
        await refreshSingleCharacter(job.character_id, job.current_character_tag);
      }
      await loadStats();
    },
    [loadStats, refreshSingleCharacter],
  );

  useEffect(() => {
    for (const job of contextV2Jobs) {
      if (
        job.kind === "regenerate" &&
        (job.status === "completed" || job.status === "failed" || job.status === "cancelled")
      ) {
        void onV2JobSettled(job);
      }
    }
  }, [contextV2Jobs, onV2JobSettled]);

  const focusedItem = items[focusIndex] ?? null;
  const focusedDraft = focusedItem ? drafts[focusedItem.id] ?? createV2DraftForItem(focusedItem) : null;
  const focusedLocked = focusedItem
    ? submittingId === focusedItem.id || isCharacterRegenerating(focusedItem.id)
    : false;
  const focusedImage = focusedItem?.images[focusedDraft?.imageIndex ?? 0] ?? null;
  const previewSrc = focusedImage ? pendingReviewImageUrl(focusedImage.image_path) : null;
  const previewAlt = focusedItem ? `${focusedItem.character_tag} original` : "";

  const openSingleMode = useCallback(() => {
    if (!focusedItem) {
      setActionMessage("현재 선택된 V2 리뷰 항목이 없습니다.");
      return;
    }
    setSingleSession({ source: "review", itemId: focusedItem.id });
  }, [focusedItem]);

  const multicolorChips = useMemo(
    () => (focusedItem ? v2AppearanceTagChips(focusedItem).filter((chip) => chip.group === "multi") : []),
    [focusedItem],
  );

  useEffect(() => {
    if (!focusedItem || !previewSrc) {
      setPreviewOpen(false);
    }
  }, [focusedItem, previewSrc]);

  useEffect(() => {
    if (focusedLocked) {
      setPreviewOpen(false);
    }
  }, [focusedLocked]);

  const togglePreview = useCallback(() => {
    if (focusedLocked) {
      return;
    }
    setPreviewOpen((open) => {
      if (open) {
        return false;
      }
      if (previewSrc) {
        setPreviewFit(true);
        return true;
      }
      return false;
    });
  }, [focusedLocked, previewSrc]);

  // Item-generic so the single-item overlay can cycle multicolor for whichever
  // candidate it currently shows (General Review focus or a pinned non-human queue
  // item), not just whatever the grid happens to have focused.
  const cycleMulticolorForItem = useCallback((item: V2ReviewCharacter, draft: V2CharacterDraft) => {
    const chips = v2AppearanceTagChips(item).filter((chip) => chip.group === "multi");
    if (chips.length === 0) {
      return;
    }
    const allChips = v2AppearanceTagChips(item);
    const enabled = new Set(draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(allChips));
    const enabledMultiIndexes = chips
      .map((chip, index) => (enabled.has(chip.key) ? index : -1))
      .filter((index) => index >= 0);
    const nextIndex = enabledMultiIndexes.length === 1 ? (enabledMultiIndexes[0] + 1) % chips.length : 0;
    for (const chip of chips) {
      enabled.delete(chip.key);
    }
    enabled.add(chips[nextIndex].key);
    updateDraft(item.id, { ...draft, enabledTags: enabled });
  }, []);

  const cycleFocusedMulticolor = useCallback(() => {
    if (!focusedItem || !focusedDraft || focusedLocked || multicolorChips.length === 0) {
      return;
    }
    cycleMulticolorForItem(focusedItem, focusedDraft);
  }, [cycleMulticolorForItem, focusedDraft, focusedItem, focusedLocked, multicolorChips]);

  const selectFocusedImage = useCallback(
    (index: number) => {
      if (!focusedItem || !focusedDraft || focusedLocked) {
        return;
      }
      if (index < 0 || index >= focusedItem.images.length) {
        return;
      }
      updateDraft(focusedItem.id, { ...focusedDraft, imageIndex: index });
    },
    [focusedDraft, focusedItem, focusedLocked],
  );

  // Parameterized so the single-item overlay can trigger regeneration for whichever
  // candidate it currently displays (General Review focus or a pinned non-human queue
  // item) without duplicating the prompt-resolution/job-start logic.
  const regenerateItem = useCallback(
    async (item: V2ReviewCharacter, draft: V2CharacterDraft) => {
      if (isCharacterRegenerating(item.id)) {
        // 실행 중 중복 재생성 시도는 무시한다.
        return;
      }
      const chips = v2AppearanceTagChips(item);
      const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
      const finalPrompt = resolveV2FinalPrompt(item, { ...draft, enabledTags });
      if (!finalPrompt.trim()) {
        setError("프롬프트가 비어 있어 재생성할 수 없습니다.");
        return;
      }
      setError(null);
      try {
        await startV2Regeneration(item.id, { base_prompt: finalPrompt });
        setPreviewOpen(false);
        setActionMessage(`${item.character_tag} 재생성 시작`);
      } catch (err) {
        const message = err instanceof Error ? err.message : "재생성에 실패했습니다.";
        if (message.toLowerCase().includes("already in progress")) {
          // 409: 백엔드에서 이미 진행 중으로 판단 - 조용히 무시한다.
          return;
        }
        setError(message);
        setActionMessage(null);
      }
    },
    [isCharacterRegenerating, startV2Regeneration],
  );

  const regenerateFocused = useCallback(async () => {
    if (!focusedItem || !focusedDraft) {
      return;
    }
    await regenerateItem(focusedItem, focusedDraft);
  }, [focusedDraft, focusedItem, regenerateItem]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !focusedItem) {
      return;
    }
    const row = node.querySelector(`[data-character-id="${focusedItem.id}"]`);
    row?.scrollIntoView({ block: "nearest" });
    if (row instanceof HTMLElement && focusCardFromKeyboardRef.current && !isEditableTarget(document.activeElement)) {
      focusCardFromKeyboardRef.current = false;
      row.focus({ preventScroll: true });
    }
  }, [focusIndex, focusedItem]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        panelMode !== "review" ||
        singleModeOpen ||
        purgeModalOpen ||
        linkingItem ||
        isEditableTarget(event.target) ||
        !focusedItem ||
        !focusedDraft
      ) {
        return;
      }

      if (event.ctrlKey && event.key === "Enter") {
        event.preventDefault();
        void bulkSaveRatedItems();
        return;
      }

      if (focusedLocked) {
        const key = event.key.toLowerCase();
        const allowed =
          event.key === "ArrowUp" ||
          event.key === "ArrowDown" ||
          event.key === "ArrowLeft" ||
          event.key === "ArrowRight" ||
          key === "q" ||
          key === "w" ||
          key === "a" ||
          key === "s";
        if (!allowed) {
          event.preventDefault();
          return;
        }
      }

      if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        event.stopPropagation();
        togglePreview();
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = Math.max(0, index - 1);
          focusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = Math.min(items.length - 1, index + 1);
          focusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = Math.max(0, index - gridCols);
          focusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = Math.min(items.length - 1, index + gridCols);
          focusCardFromKeyboardRef.current = next !== index;
          return next;
        });
        return;
      }

      if (event.ctrlKey && event.key >= "1" && event.key <= "9") {
        event.preventDefault();
        selectFocusedImage(Number(event.key) - 1);
        return;
      }

      const ratingAlias = event.key.toLowerCase();
      if (event.key >= "0" && event.key <= "6") {
        event.preventDefault();
        setRating(focusedItem.id, Number(event.key));
        return;
      }

      if (ratingAlias === "z" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        setRating(focusedItem.id, 0);
        return;
      }

      if (event.key === "-" || (ratingAlias === "x" && !event.ctrlKey && !event.metaKey && !event.altKey)) {
        event.preventDefault();
        setRating(focusedItem.id, -1);
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        void completeItem(focusedItem);
        return;
      }

      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        openSingleMode();
        return;
      }
      if (key === "g") {
        event.preventDefault();
        updateDraft(focusedItem.id, { ...focusedDraft, gender: cycleGender(focusedDraft.gender) });
        return;
      }
      if (key === "c") {
        event.preventDefault();
        setPreviewOpen(false);
        cycleFocusedMulticolor();
        return;
      }
      if (key === "r") {
        event.preventDefault();
        void regenerateFocused();
        return;
      }
      if (key === "q") {
        event.preventDefault();
        window.open(
          `https://danbooru.donmai.us/posts?tags=${encodeURIComponent(
            `${focusedItem.character_tag} solo`.trim(),
          )}`,
          "_blank",
          "noopener,noreferrer",
        );
        return;
      }
      if (key === "w") {
        event.preventDefault();
        window.open(
          focusedItem.danbooru_wiki_url ||
            `https://danbooru.donmai.us/wiki_pages/${encodeURIComponent(focusedItem.character_tag)}`,
          "_blank",
          "noopener,noreferrer",
        );
        return;
      }
      if (key === "a") {
        event.preventDefault();
        setLinkingItemSource("review");
        setLinkingItem(focusedItem);
      }
    };

    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [
    bulkSaveRatedItems,
    cycleFocusedMulticolor,
    focusedDraft,
    focusedItem,
    focusedLocked,
    gridCols,
    items.length,
    linkingItem,
    openSingleMode,
    panelMode,
    purgeModalOpen,
    regenerateFocused,
    selectFocusedImage,
    singleModeOpen,
    togglePreview,
  ]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;

  useEffect(() => {
    setPageInput(String(currentPage));
  }, [currentPage]);

  const goToPage = useCallback(
    (value: string) => {
      const parsed = Number.parseInt(value, 10);
      const page = Number.isFinite(parsed) ? Math.min(pageCount, Math.max(1, parsed)) : currentPage;
      setPageInput(String(page));
      setSkip((page - 1) * PAGE_SIZE);
    },
    [currentPage, pageCount],
  );

  const renderPaginationControls = () => (
    <div className="series-pagination-controls" aria-label="V2 review pagination">
      <button className="btn btn-small" type="button" disabled={skip === 0} onClick={() => setSkip(0)}>&laquo;</button>
      <button
        className="btn btn-small"
        type="button"
        disabled={skip === 0}
        onClick={() => setSkip((s) => Math.max(0, s - PAGE_SIZE))}
      >
        &lsaquo;
      </button>
      <input
        className="series-pagination-page-input"
        type="number"
        min="1"
        max={pageCount}
        value={pageInput}
        aria-label="V2 review page number"
        onChange={(event) => setPageInput(event.target.value)}
        onBlur={(event) => goToPage(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.currentTarget.blur();
          }
        }}
      />
      <span className="series-pagination-page-total">/ {pageCount}</span>
      <button
        className="btn btn-small"
        type="button"
        disabled={currentPage >= pageCount}
        onClick={() => setSkip((s) => Math.min((pageCount - 1) * PAGE_SIZE, s + PAGE_SIZE))}
      >
        &rsaquo;
      </button>
      <button
        className="btn btn-small"
        type="button"
        disabled={currentPage >= pageCount}
        onClick={() => setSkip((pageCount - 1) * PAGE_SIZE)}
      >
        &raquo;
      </button>
    </div>
  );

  const gridStyle = { "--v2-card-width": `${effectiveCardWidthPx}px` } as CSSProperties;
  const visibleDirtyCount = items.filter((item) => dirtyIds.has(item.id)).length;
  const visibleFailedCount = items.filter((item) => item.id in failedMessages).length;
  const visibleSavingCount = items.filter((item) => savingIds.has(item.id)).length;
  const remainingLabel = reviewStatus === "pending" && stats ? `${stats.pending.toLocaleString()}개 대기` : `${total.toLocaleString()}개 결과`;
  const activeFilters = [
    `상태 ${reviewStatus === "pending" ? "대기" : reviewStatus === "completed_recent" ? "최근 완료" : reviewStatus}`,
    ratingFilter ? `레이팅 ${ratingFilter}` : null,
    qualityStatus ? `품질 ${qualityStatus}` : null,
    identityStatus ? `재현 ${identityStatus}` : null,
    generationStatus ? `생성 ${generationStatus}` : null,
    genderFilter ? `성별 ${genderFilter}` : null,
    nonHumanFilter !== "all" ? `분류 ${nonHumanFilter === "human" ? "인간" : "비인간"}` : null,
    seriesId ? `시리즈 #${seriesId}` : null,
    multicolorFilter ? `multicolor ${multicolorFilter}` : null,
    promptModifiedOnly ? "프롬프트 수정됨" : null,
    search ? `검색 ${search}` : null,
  ].filter(Boolean);
  const statsSummary = stats
    ? `전체 ${stats.total.toLocaleString()} · 대기 ${stats.pending.toLocaleString()} · 진행 ${stats.in_progress.toLocaleString()} · 완료 ${stats.completed.toLocaleString()}`
    : "통계 로딩 중";
  const workSummary = `남은 항목: ${remainingLabel} · 현재 페이지 ${currentPage}/${pageCount} · 표시 ${items.length.toLocaleString()}개 · 미저장 ${visibleDirtyCount} · 저장 중 ${visibleSavingCount} · 실패 ${visibleFailedCount}`;

  const getSaveStatus = (item: V2ReviewCharacter, regenerateJob?: V2GenerationJobState): V2ReviewCardSaveStatus => {
    if (regenerateJob && (regenerateJob.status === "queued" || regenerateJob.status === "running" || regenerateJob.status === "paused")) {
      const detail =
        regenerateJob.total > 0 ? `${regenerateJob.current}/${regenerateJob.total}` : regenerateJob.message || undefined;
      return { kind: "regenerating", label: "재생성 중", detail };
    }
    if (savingIds.has(item.id) || submittingId === item.id) {
      return { kind: "saving", label: "저장 중" };
    }
    if (failedMessages[item.id]) {
      return { kind: "failed", label: "저장 실패", detail: failedMessages[item.id] };
    }
    if (dirtyIds.has(item.id)) {
      return { kind: "dirty", label: "미저장 변경" };
    }
    return item.review_status === "completed"
      ? { kind: "clean", label: "저장됨" }
      : { kind: "clean", label: "변경 없음" };
  };

  const nhPageCount = Math.max(1, Math.ceil(nhTotal / PAGE_SIZE));
  const nhCurrentPage = Math.floor(nhSkip / PAGE_SIZE) + 1;

  const singleModeSaveStatus: V2ReviewCardSaveStatus | null = singleModeItem
    ? singleModeIsNonHuman
      ? nhOverlayBulkSaving
        ? { kind: "saving", label: "변경사항 적용 중" }
        : nhOverlayFailedMessages[singleModeItem.id]
          ? { kind: "failed", label: "적용 실패", detail: nhOverlayFailedMessages[singleModeItem.id] }
          : singleModeNonHumanDecision?.action === "exclude"
            ? { kind: "dirty", label: "임시 저장: 후보 제외" }
            : singleModeDisplayDraft && isDraftChanged(singleModeItem, singleModeDisplayDraft)
              ? { kind: "dirty", label: "미저장 변경" }
              : { kind: "clean", label: "변경 없음" }
      : getSaveStatus(singleModeItem, v2JobsByCharacter[singleModeItem.id])
    : null;

  const singleReviewOverlay = singleModeOpen && singleModeItem && singleModeDisplayDraft && singleModeSaveStatus ? (
    <V2SingleReviewOverlay
      open={singleModeOpen}
      item={singleModeItem}
      rowIndex={singleModeRowIndex}
      globalIndex={singleModeGlobalIndex}
      total={singleModeTotal}
      draft={singleModeDisplayDraft}
      thumbSize={thumbSize}
      filters={reviewListFilters}
      locked={singleModeLocked}
      saveStatus={singleModeSaveStatus}
      regenerateMessage={v2JobsByCharacter[singleModeItem.id]?.message}
      regenerateProgress={
        v2JobsByCharacter[singleModeItem.id] && v2JobsByCharacter[singleModeItem.id].total > 0
          ? { current: v2JobsByCharacter[singleModeItem.id].current, total: v2JobsByCharacter[singleModeItem.id].total }
          : null
      }
      regenerating={isCharacterRegenerating(singleModeItem.id)}
      suspended={Boolean(linkingItem)}
      readOnly={false}
      disableNeighborPreload={singleModeIsNonHuman}
      canNavigatePrevious={!singleModeIsNonHuman || singleModeRowIndex > 0}
      canNavigateNext={!singleModeIsNonHuman || singleModeRowIndex < nhItems.length - 1}
      onClose={closeSingleSession}
      onNavigateLocal={singleModeIsNonHuman ? nhNavigateSingleLocal : navigateSingleLocal}
      onNavigatePage={singleModeIsNonHuman ? undefined : navigateSinglePage}
      onDraftChange={(next) => updateDraft(singleModeItem.id, next)}
      onToggleTag={(tagKey) => toggleTag(singleModeItem, tagKey)}
      onRate={
        singleModeIsNonHuman
          ? (value) => setNonHumanOverlayRating(singleModeItem, value)
          : (value) => setRating(singleModeItem.id, value)
      }
      onCycleMulticolor={
        singleModeIsNonHuman
          ? () => cycleMulticolorForItem(singleModeItem, singleModeDisplayDraft)
          : cycleFocusedMulticolor
      }
      onRegenerate={() => void regenerateItem(singleModeItem, singleModeDisplayDraft)}
      onComplete={
        singleModeIsNonHuman
          ? () => void completeNonHumanSingleItem(singleModeItem)
          : () => void completeItem(singleModeItem)
      }
      onBulkComplete={singleModeIsNonHuman ? undefined : () => void bulkSaveRatedItems()}
      onNonHumanExclude={
        singleModeIsNonHuman
          ? () => {
              if (nhOverlayBulkSaving) return;
              stageNonHumanOverlayExclude(singleModeItem);
            }
          : undefined
      }
      onNonHumanBulkApply={singleModeIsNonHuman ? () => void applyNonHumanOverlayDecisions() : undefined}
      onOpenLinkModal={() => {
        setLinkingItemSource(singleModeIsNonHuman ? "non_human" : "review");
        setLinkingItem(singleModeItem);
      }}
    />
  ) : null;

  return (
    <>
      {panelMode === "non_human" ? (
        <>
          <div className="toolbar review-toolbar v2-non-human-toolbar">
            <div className="field">
              <label htmlFor="v2-non-human-search">검색</label>
              <input
                id="v2-non-human-search"
                value={nhSearch}
                onChange={(event) => setNhSearch(event.target.value)}
                placeholder="character tag"
              />
            </div>
            <div className="field">
              <label htmlFor="v2-non-human-rating-status">평점</label>
              <select
                id="v2-non-human-rating-status"
                value={nhRatingStatus}
                onChange={(event) => setNhRatingStatus(event.target.value as NonHumanRatingFilter)}
              >
                <option value="all">전체</option>
                <option value="rated">평점 있음</option>
                <option value="unrated">평점 없음</option>
              </select>
            </div>
            <div className="field" style={{ justifyContent: "flex-end" }}>
              <label>&nbsp;</label>
              <button
                className="btn"
                type="button"
                disabled={nhRecalculating}
                onClick={() => void recalculateNonHumanCandidates()}
              >
                {nhRecalculating ? "후보 분리 중..." : "후보 재계산 / 분리"}
              </button>
              <button className="btn" type="button" disabled={nhRecalculating} onClick={() => void loadNonHumanQueue()}>
                새로고침
              </button>
            </div>
            <div className="series-pagination-controls" aria-label="비인간 후보 큐 pagination">
              <button
                className="btn btn-small"
                type="button"
                disabled={nhSkip === 0}
                onClick={() => setNhSkip(0)}
              >
                &laquo;
              </button>
              <button
                className="btn btn-small"
                type="button"
                disabled={nhSkip === 0}
                onClick={() => setNhSkip((s) => Math.max(0, s - PAGE_SIZE))}
              >
                &lsaquo;
              </button>
              <span className="series-pagination-page-total">
                {nhCurrentPage} / {nhPageCount}
              </span>
              <button
                className="btn btn-small"
                type="button"
                disabled={nhCurrentPage >= nhPageCount}
                onClick={() => setNhSkip((s) => Math.min((nhPageCount - 1) * PAGE_SIZE, s + PAGE_SIZE))}
              >
                &rsaquo;
              </button>
            </div>
            <div className="catalog-review-progress">
              <div>비인간 후보 대기 {nhTotal.toLocaleString()}개</div>
              <div>
                표시 {nhItems.length.toLocaleString()}개
                {nhFocusedItem ? ` · 현재 ${nhFocusedItem.character_tag}` : ""}
              </div>
            </div>
          </div>

          <details className="review-shortcut-guide" open>
            <summary className="review-shortcut-guide-summary">
              <span className="review-shortcut-guide-title">단축키</span>
              <span className="review-shortcut-guide-hint">
                s 상세 · 상세 0–6/z/x 레이팅 · g 성별 · c 다중색 · a 부모 연결 · e 후보 제외 · Ctrl+Enter 일괄 적용
              </span>
            </summary>
            <div className="review-shortcut-guide-body">
              <span>그리드 Enter/3/x/e는 빠른 즉시 처리, s 상세 팝업은 일반 검수와 같은 편집 기능 사용</span>
              <span>상세 0–6 · z=0 · -=x=-1 · g 성별 · c 다중색 · a 부모 연결</span>
              <span>상세 e 후보 제외 임시 지정 · 레이팅을 다시 선택하면 제외 취소</span>
              <span>상세 Enter 현재 항목 저장 · Ctrl+Enter 레이팅된 임시 변경 일괄 적용</span>
              <span>r 현재 이미지 재생성 · ←→ 항목 이동</span>
              <span>Space 이미지 확대</span>
              <span>q/w Danbooru 게시물/위키</span>
            </div>
          </details>

          {nhError ? <div className="error-banner">{nhError}</div> : null}
          {nhActionMessage ? (
            <div className="catalog-card-subtitle" style={{ marginBottom: 8 }}>
              {nhActionMessage}
            </div>
          ) : null}

          {nhLoading ? (
            <div className="empty-state">Loading non-human queue...</div>
          ) : nhItems.length === 0 ? (
            <div className="empty-state panel">대기 중인 비인간 후보가 없습니다.</div>
          ) : (
            <div ref={scrollRef} className="v2-review-grid v2-non-human-grid">
              {nhItems.map((item, rowIndex) => (
                <NonHumanQueueCard
                  key={item.id}
                  item={item}
                  focused={rowIndex === nhFocusIndex}
                  acting={nhActingIds.has(item.id)}
                  failedMessage={nhFailedMessages[item.id]}
                  onSelect={() => setNhFocusIndex(rowIndex)}
                  onConfirmProposed={() => {
                    setNhFocusIndex(rowIndex);
                    const suggested = item.non_human_suggested_rating;
                    if (suggested !== -1 && suggested !== 3) {
                      setNhActionMessage("제안된 레이팅이 없습니다. -1 또는 3을 직접 선택하세요.");
                      return;
                    }
                    void nhConfirm(item, suggested);
                  }}
                  onConfirm={(rating) => {
                    setNhFocusIndex(rowIndex);
                    void nhConfirm(item, rating);
                  }}
                  onExclude={() => {
                    setNhFocusIndex(rowIndex);
                    void nhExclude(item);
                  }}
                  onOpenDetails={() => openNonHumanDetails(item)}
                />
              ))}
            </div>
          )}

          {nhPreviewOpen && nhPreviewSrc ? (
            <ReviewImagePreview
              src={nhPreviewSrc}
              alt={nhPreviewAlt}
              original
              fitToScreen={nhPreviewFit}
              onToggleFit={() => setNhPreviewFit((fit) => !fit)}
              onClose={() => setNhPreviewOpen(false)}
            />
          ) : null}

          {nhTotal > PAGE_SIZE ? (
            <div className="series-pagination">
              <div className="series-pagination-controls" aria-label="비인간 후보 큐 pagination">
                <button className="btn btn-small" type="button" disabled={nhSkip === 0} onClick={() => setNhSkip(0)}>
                  &laquo;
                </button>
                <button
                  className="btn btn-small"
                  type="button"
                  disabled={nhSkip === 0}
                  onClick={() => setNhSkip((s) => Math.max(0, s - PAGE_SIZE))}
                >
                  &lsaquo;
                </button>
                <span className="series-pagination-page-total">
                  {nhCurrentPage} / {nhPageCount}
                </span>
                <button
                  className="btn btn-small"
                  type="button"
                  disabled={nhCurrentPage >= nhPageCount}
                  onClick={() => setNhSkip((s) => Math.min((nhPageCount - 1) * PAGE_SIZE, s + PAGE_SIZE))}
                >
                  &rsaquo;
                </button>
              </div>
            </div>
          ) : null}
        </>
      ) : (
      <>
      <div className="toolbar review-toolbar">
        <div className="field">
          <label htmlFor="v2-review-human-type">분류</label>
          <select
            id="v2-review-human-type"
            value={nonHumanFilter}
            onChange={(event) => setNonHumanFilter(event.target.value as V2NonHumanFilter)}
          >
            <option value="all">전체</option>
            <option value="human">인간</option>
            <option value="non_human">비인간</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-status">리뷰 상태</label>
          <select
            id="v2-review-status"
            value={reviewStatus}
            onChange={(event) => setReviewStatus(event.target.value as V2ReviewStatus)}
          >
            <option value="pending">대기 중</option>
            <option value="completed_recent">완료(최근순)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-search">검색</label>
          <input
            id="v2-review-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="character tag"
          />
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadReviews()}>
            새로고침
          </button>
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={openSingleMode}>
            단일 항목 보기
          </button>
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button
            className="btn btn-primary"
            type="button"
            disabled={bulkSaving}
            title="Ctrl+Enter"
            onClick={() => void bulkSaveRatedItems()}
          >
            {bulkSaving ? "저장 중..." : "레이팅된 항목 일괄 저장 (Ctrl+Enter)"}
          </button>
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button
            className="btn"
            type="button"
            onClick={() => setPurgeModalOpen(true)}
            title="V2 현재 검색어 기준으로 선택되지 않은 이미지를 미리보고 골라서 삭제합니다."
          >
            미선택 이미지 삭제
          </button>
        </div>
        {renderPaginationControls()}
        <div className="catalog-review-progress">
          <div>{statsSummary}</div>
          <div>
            {workSummary}
            {focusedItem ? ` · 현재 ${focusedItem.character_tag}` : ""}
          </div>
          <div>필터: {activeFilters.length > 0 ? activeFilters.join(" · ") : "없음"}</div>
        </div>
      </div>

      <details className="review-rating-guide">
        <summary className="review-rating-guide-summary">
          <span className="review-rating-guide-title">상세 필터</span>
          <span className="review-rating-guide-hint">레이팅 · 품질 · 재현 · 성별 · 시리즈 · multicolor · 프롬프트</span>
        </summary>
        <div className="toolbar review-toolbar">
          <div className="field">
          <label htmlFor="v2-review-rating">레이팅</label>
          <select id="v2-review-rating" value={ratingFilter} onChange={(event) => setRatingFilter(event.target.value)}>
            <option value="">전체</option>
            <option value="unrated">미지정</option>
            {[-1, 0, 1, 2, 3, 4, 5, 6].map((value) => (
              <option key={value} value={String(value)}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-quality">품질 상태</label>
          <select
            id="v2-review-quality"
            value={qualityStatus}
            onChange={(event) => setQualityStatus(event.target.value)}
          >
            <option value="">전체</option>
            <option value="pass">Pass</option>
            <option value="warning">Warning</option>
            <option value="reject">Reject</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-identity">재현 상태</label>
          <select
            id="v2-review-identity"
            value={identityStatus}
            onChange={(event) => setIdentityStatus(event.target.value)}
          >
            <option value="">전체</option>
            <option value="pass">Pass</option>
            <option value="warning">Warning</option>
            <option value="reject">Reject</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-generation">생성 상태</label>
          <select
            id="v2-review-generation"
            value={generationStatus}
            onChange={(event) => setGenerationStatus(event.target.value)}
          >
            <option value="">전체</option>
            <option value="not_generated">not_generated</option>
            <option value="generating">generating</option>
            <option value="generated">generated</option>
            <option value="generation_failed">generation_failed</option>
            <option value="likely_untrained">likely_untrained</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-gender">성별</label>
          <select id="v2-review-gender" value={genderFilter} onChange={(event) => setGenderFilter(event.target.value)}>
            <option value="">전체</option>
            <option value="1girl">1girl</option>
            <option value="1boy">1boy</option>
            <option value="no_humans">no_humans</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="v2-review-multicolor">Multicolor</label>
          <select
            id="v2-review-multicolor"
            value={multicolorFilter}
            onChange={(event) => setMulticolorFilter(event.target.value)}
          >
            <option value="">전체</option>
            <option value="has">보유</option>
            <option value="suggested">추천 있음</option>
          </select>
        </div>
        <div className="field review-series-field">
          <label>시리즈</label>
          <SeriesSearchSelect
            value={seriesId}
            onChange={(id: number | "", _series?: Series | null) => setSeriesId(id)}
          />
        </div>
        <div className="field">
          <label htmlFor="v2-review-prompt-modified">&nbsp;</label>
          <label className="review-checkbox-field">
            <input
              id="v2-review-prompt-modified"
              type="checkbox"
              checked={promptModifiedOnly}
              onChange={(event) => setPromptModifiedOnly(event.target.checked)}
            />
            프롬프트 수정됨만
          </label>
        </div>
          <ReviewShortcutGuide includeMerge includeMulticolor v2Layout />
        </div>
      </details>

      <V2RatingGuide />

      {error ? <div className="error-banner">{error}</div> : null}
      {actionMessage ? <div className="catalog-card-subtitle" style={{ marginBottom: 8 }}>{actionMessage}</div> : null}

      {loading ? (
        <div className="empty-state">Loading V2 reviews...</div>
      ) : items.length === 0 ? (
        <div className="empty-state panel">검수할 캐릭터가 없습니다.</div>
      ) : (
        <div ref={scrollRef} className="v2-review-grid" style={gridStyle}>
          {items.map((item, rowIndex) => {
            const draft = drafts[item.id] ?? createV2DraftForItem(item);
            const focused = rowIndex === focusIndex;
            const locked = submittingId === item.id || savingIds.has(item.id) || isCharacterRegenerating(item.id);
            const regenerateJob = v2JobsByCharacter[item.id];
            const saveStatus = getSaveStatus(item, regenerateJob);
            return (
              <V2ReviewRow
                key={item.id}
                item={item}
                rowIndex={rowIndex}
                focused={focused}
                draft={draft}
                thumbSize={thumbSize}
                locked={locked}
                saveStatus={saveStatus}
                regenerateMessage={regenerateJob?.message}
                regenerateProgress={
                  regenerateJob && regenerateJob.total > 0
                    ? { current: regenerateJob.current, total: regenerateJob.total }
                    : null
                }
                onSelect={() => setFocusIndex(rowIndex)}
                onDraftChange={(next) => updateDraft(item.id, next)}
                onToggleTag={(tagKey) => toggleTag(item, tagKey)}
                onRate={(value) => setRating(item.id, value)}
                onRegenerate={focused ? () => void regenerateFocused() : undefined}
                onComplete={() => void completeItem(item)}
                onOpenLinkModal={() => {
                  setLinkingItemSource("review");
                  setLinkingItem(item);
                }}
                regenerating={locked}
              />
            );
          })}
        </div>
      )}

      {previewOpen && previewSrc ? (
        <ReviewImagePreview
          src={previewSrc}
          alt={previewAlt}
          original
          fitToScreen={previewFit}
          onToggleFit={() => setPreviewFit((fit) => !fit)}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}

      {purgeModalOpen ? (
        <PurgeUnselectedModal
          title="미선택 이미지 삭제"
          description={`V2 리뷰 · ${search.trim() ? `현재 검색어: ${search.trim()}` : "현재 검색어 없음"}`}
          fetchPreview={fetchPurgePreview}
          onSubmit={submitPurgeSelected}
          onClose={() => setPurgeModalOpen(false)}
          onCompleted={handlePurgeCompleted}
        />
      ) : null}

      {total > PAGE_SIZE ? (
        <div className="series-pagination">
          {renderPaginationControls()}
        </div>
      ) : null}
      </>
      )}
      {linkingItem ? (
        <CharacterLinkModal
          character={toLinkableSummary(linkingItem)}
          onClose={() => setLinkingItem(null)}
          onLinked={() => {
            if (linkingItemSource === "non_human") {
              void loadNonHumanQueue(linkingItem.id);
            } else {
              void loadReviews(linkingItem.id);
            }
          }}
        />
      ) : null}
      {singleReviewOverlay}
    </>
  );
}
