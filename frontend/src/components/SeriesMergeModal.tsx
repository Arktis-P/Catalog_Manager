import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Series, SeriesMergeCandidate, SeriesMergePreview } from "../types";

type MergeMode = "into_parent" | "absorb_child";

interface SeriesMergeModalProps {
  seriesList: Series[];
  onClose: () => void;
  onMerged: () => void;
}

function canMergeSeries(series: Series): boolean {
  return !series.is_merged_child && (series.status === "collected" || series.status === "tagged");
}

function pickAnchorSeries(seriesList: Series[]): Series {
  return [...seriesList].sort((left, right) => right.post_count - left.post_count)[0];
}

export function SeriesMergeModal({ seriesList, onClose, onMerged }: SeriesMergeModalProps) {
  const mergeableSeries = useMemo(
    () => seriesList.filter((item) => canMergeSeries(item)),
    [seriesList],
  );
  const isBulkMerge = mergeableSeries.length > 1;
  const anchorSeries = useMemo(() => pickAnchorSeries(mergeableSeries), [mergeableSeries]);
  const sourceIds = useMemo(() => new Set(mergeableSeries.map((item) => item.id)), [mergeableSeries]);

  const [mode, setMode] = useState<MergeMode>("into_parent");
  const [search, setSearch] = useState("");
  const [candidates, setCandidates] = useState<SeriesMergeCandidate[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [previews, setPreviews] = useState<SeriesMergePreview[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [mergeProgress, setMergeProgress] = useState(0);
  const [mergeStepLabel, setMergeStepLabel] = useState("");
  const [error, setError] = useState<string | null>(null);

  const effectiveMode: MergeMode = isBulkMerge ? "into_parent" : mode;

  const selectedCandidate = useMemo(
    () => candidates.find((item) => item.id === selectedId) ?? null,
    [candidates, selectedId],
  );

  const childIdsForMerge = useMemo(() => {
    if (effectiveMode === "into_parent") {
      if (!selectedId) {
        return [];
      }
      return mergeableSeries.filter((item) => item.id !== selectedId).map((item) => item.id);
    }
    return selectedId ? [selectedId] : [];
  }, [effectiveMode, mergeableSeries, selectedId]);

  const previewTotals = useMemo(
    () =>
      previews.reduce(
        (acc, preview) => ({
          moved: acc.moved + preview.moved_count,
          duplicate: acc.duplicate + preview.duplicate_count,
          characters: acc.characters + preview.child_character_count,
        }),
        { moved: 0, duplicate: 0, characters: 0 },
      ),
    [previews],
  );

  useEffect(() => {
    if (mergeableSeries.length === 0) {
      return;
    }
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const excludeIds = effectiveMode === "absorb_child" ? [anchorSeries.id] : undefined;
        const response = await api.listSeriesMergeCandidates(anchorSeries.id, {
          mode: effectiveMode === "into_parent" ? "parent" : "child",
          search: search || undefined,
          exclude_ids: excludeIds,
          limit: search ? 100 : 50,
        });
        if (cancelled) return;

        const nextCandidates =
          effectiveMode === "absorb_child"
            ? response.items.filter((item) => !sourceIds.has(item.id))
            : response.items;

        setCandidates(nextCandidates);
        setSelectedId((current) => {
          if (current && nextCandidates.some((item) => item.id === current)) {
            return current;
          }
          return nextCandidates[0]?.id ?? null;
        });
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load merge candidates");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [anchorSeries.id, effectiveMode, mergeableSeries, search, sourceIds]);

  useEffect(() => {
    if (effectiveMode === "into_parent") {
      if (!selectedId || childIdsForMerge.length === 0) {
        setPreviews([]);
        return;
      }
    } else if (!selectedId) {
      setPreviews([]);
      return;
    }

    if (selectedCandidate && !selectedCandidate.mergeable) {
      setPreviews([]);
      setError(
        selectedCandidate.status === "pending"
          ? `선택한 시리즈에 수집된 캐릭터가 없어 병합 상위로 사용할 수 없습니다. Collect 후 다시 시도하세요.`
          : `선택한 시리즈는 status가 ${selectedCandidate.status}입니다. 병합하려면 collected 또는 tagged 상태여야 합니다.`,
      );
      return;
    }

    let cancelled = false;
    const loadPreviews = async () => {
      try {
        const nextPreviews: SeriesMergePreview[] = [];
        if (effectiveMode === "into_parent") {
          for (const childId of childIdsForMerge) {
            const result = await api.previewSeriesMerge(childId, selectedId!);
            nextPreviews.push(result);
          }
        } else {
          const result = await api.previewSeriesMerge(selectedId!, anchorSeries.id);
          nextPreviews.push(result);
        }
        if (!cancelled) {
          setPreviews(nextPreviews);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setPreviews([]);
          setError(err instanceof Error ? err.message : "Failed to preview merge");
        }
      }
    };
    void loadPreviews();
    return () => {
      cancelled = true;
    };
  }, [selectedId, effectiveMode, childIdsForMerge, anchorSeries.id, selectedCandidate]);

  const handleSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || candidates.length === 0) {
      return;
    }
    event.preventDefault();
    const exact = candidates.find(
      (candidate) => candidate.series_tag.toLowerCase() === search.trim().toLowerCase(),
    );
    setSelectedId(exact?.id ?? candidates[0]?.id ?? null);
  };

  useEffect(() => {
    if (!submitting) {
      setMergeProgress(0);
      setMergeStepLabel("");
      return;
    }
    setMergeProgress(8);
    const timer = window.setInterval(() => {
      setMergeProgress((current) => {
        if (current >= 90) return current;
        return current + 4 + Math.random() * 6;
      });
    }, 350);
    return () => window.clearInterval(timer);
  }, [submitting]);

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const handleSubmit = async () => {
    if (!selectedId || previews.length === 0) return;
    setSubmitting(true);
    setMergeProgress(8);
    setError(null);
    try {
      const jobs =
        effectiveMode === "into_parent"
          ? childIdsForMerge.map((childId) => ({ childId, parentId: selectedId! }))
          : [{ childId: selectedId!, parentId: anchorSeries.id }];

      for (let index = 0; index < jobs.length; index += 1) {
        const job = jobs[index]!;
        const preview = previews.find((item) => item.child_series_id === job.childId);
        setMergeStepLabel(
          preview
            ? `${preview.child_series_tag} → ${preview.parent_series_tag} (${index + 1}/${jobs.length})`
            : `${index + 1}/${jobs.length}`,
        );
        setMergeProgress(8 + ((index + 0.5) / jobs.length) * 82);
        await api.mergeSeries(job.childId, job.parentId);
      }
      setMergeProgress(100);
      onMerged();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to merge series");
    } finally {
      setSubmitting(false);
    }
  };

  if (mergeableSeries.length === 0) {
    return null;
  }

  const title =
    mergeableSeries.length === 1
      ? `Merge Series — ${mergeableSeries[0]!.series_tag}`
      : `Merge ${mergeableSeries.length} Series`;

  const parentTag =
    effectiveMode === "into_parent"
      ? selectedCandidate?.series_tag
      : anchorSeries.series_tag;

  return (
    <div className="modal-backdrop" onClick={handleClose}>
      <div className="modal modal-wide" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header-row">
          <div>
            <h2 className="modal-title">{title}</h2>
            <p className="catalog-card-subtitle">
              collected/tagged 시리즈끼리 병합합니다. 중복 캐릭터는 상위 시리즈 쪽을 유지합니다.
            </p>
            {isBulkMerge ? (
              <p className="catalog-card-subtitle" style={{ marginTop: 6 }}>
                병합 대상:{" "}
                {mergeableSeries.map((item) => item.series_tag).join(", ")}
              </p>
            ) : null}
          </div>
          <button className="btn btn-small" type="button" disabled={submitting} onClick={handleClose}>
            Close
          </button>
        </div>

        {!isBulkMerge ? (
          <div className="merge-mode-toggle">
            <label>
              <input
                type="radio"
                name="merge-mode"
                checked={mode === "into_parent"}
                disabled={submitting}
                onChange={() => setMode("into_parent")}
              />
              이 시리즈를 다른 시리즈의 하위로 병합
            </label>
            <label>
              <input
                type="radio"
                name="merge-mode"
                checked={mode === "absorb_child"}
                disabled={submitting}
                onChange={() => setMode("absorb_child")}
              />
              다른 시리즈를 이 시리즈로 흡수 (상위 시리즈가 됨)
            </label>
          </div>
        ) : null}

        <div className="toolbar" style={{ marginBottom: 12 }}>
          <div className="field full-width">
            <label htmlFor="merge-search">
              {effectiveMode === "into_parent" ? "상위 시리즈 검색" : "하위 시리즈 검색"}
            </label>
            <input
              id="merge-search"
              value={search}
              disabled={submitting}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="series tag 입력 (예: fate_(series)) 후 Enter 또는 목록에서 선택"
              autoComplete="off"
            />
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}

        <div className="field full-width">
          <label>
            {effectiveMode === "into_parent" ? "병합될 상위 시리즈" : "흡수할 하위 시리즈"}
          </label>
          {loading ? <div className="empty-state">후보 불러오는 중...</div> : null}
          {!loading ? (
            <div className="merge-candidate-list" role="listbox" aria-label="merge target candidates">
              {candidates.length === 0 ? (
                <div className="empty-state">
                  검색 조건에 맞는 시리즈가 없습니다. series tag를 정확히 입력해 보세요.
                </div>
              ) : (
                candidates.map((candidate) => {
                  const isSelected = candidate.id === selectedId;
                  const isExactMatch =
                    search.trim().length > 0 &&
                    candidate.series_tag.toLowerCase() === search.trim().toLowerCase();
                  return (
                    <button
                      key={candidate.id}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      className={`merge-candidate-item${isSelected ? " merge-candidate-item-selected" : ""}${
                        !candidate.mergeable ? " merge-candidate-item-disabled" : ""
                      }`}
                      disabled={submitting}
                      onClick={() => setSelectedId(candidate.id)}
                    >
                      <span className="merge-candidate-tag">
                        {candidate.series_tag}
                        {isExactMatch ? " · exact" : ""}
                      </span>
                      {candidate.display_name ? (
                        <span className="merge-candidate-meta">{candidate.display_name}</span>
                      ) : null}
                      <span className="merge-candidate-stats">
                        posts {candidate.post_count.toLocaleString()}
                        {" · "}
                        {candidate.character_count.toLocaleString()} chars
                        {" · "}
                        status {candidate.status}
                        {!candidate.mergeable ? " · 병합 불가" : ""}
                        {candidate.similarity_score > 0
                          ? ` · match ${Math.round(candidate.similarity_score * 100)}%`
                          : ""}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          ) : null}
        </div>

        {previews.length > 0 ? (
          <div className="merge-preview-panel">
            <div>
              <strong>Preview</strong>
            </div>
            {previews.length === 1 && previews[0] ? (
              <>
                <div className="catalog-card-subtitle">
                  Child: {previews[0].child_series_tag} ({previews[0].child_character_count} characters)
                </div>
                <div className="catalog-card-subtitle">Parent: {previews[0].parent_series_tag}</div>
                <div>
                  이동 {previews[0].moved_count.toLocaleString()} · 중복 제외{" "}
                  {previews[0].duplicate_count.toLocaleString()}
                </div>
              </>
            ) : (
              <>
                <div className="catalog-card-subtitle">Parent: {parentTag}</div>
                <div className="catalog-card-subtitle">
                  하위 {previews.length}개 시리즈 · 캐릭터 {previewTotals.characters.toLocaleString()}명
                </div>
                <div>
                  총 이동 {previewTotals.moved.toLocaleString()} · 중복 제외{" "}
                  {previewTotals.duplicate.toLocaleString()}
                </div>
                <ul className="merge-preview-child-list">
                  {previews.map((preview) => (
                    <li key={preview.child_series_id}>
                      {preview.child_series_tag}: 이동 {preview.moved_count.toLocaleString()} · 중복{" "}
                      {preview.duplicate_count.toLocaleString()}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        ) : null}

        {selectedCandidate ? (
          <div className="catalog-card-subtitle" style={{ marginTop: 8 }}>
            선택: {selectedCandidate.series_tag} · status {selectedCandidate.status} · posts{" "}
            {selectedCandidate.post_count.toLocaleString()}
          </div>
        ) : null}

        <div className="modal-actions merge-modal-actions">
          <div className="merge-progress-area">
            {submitting ? (
              <>
                <div className="merge-progress-label">
                  병합 중…
                  {mergeStepLabel ? ` ${mergeStepLabel}` : null}
                  {!mergeStepLabel && previews.length === 1 && previews[0]
                    ? ` ${previews[0].child_series_tag} → ${previews[0].parent_series_tag}`
                    : null}
                </div>
                <div
                  className="merge-progress-track"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(mergeProgress)}
                >
                  <div
                    className={`merge-progress-fill${mergeProgress >= 100 ? " merge-progress-fill-done" : ""}`}
                    style={{ width: `${Math.min(mergeProgress, 100)}%` }}
                  />
                </div>
              </>
            ) : null}
          </div>
          <div className="merge-modal-buttons">
            <button className="btn" type="button" disabled={submitting} onClick={handleClose}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              type="button"
              disabled={
                !selectedId ||
                previews.length === 0 ||
                submitting ||
                (selectedCandidate ? !selectedCandidate.mergeable : false)
              }
              onClick={() => void handleSubmit()}
            >
              {submitting
                ? "Merging..."
                : isBulkMerge
                  ? `Merge ${childIdsForMerge.length} into parent`
                  : "Merge"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function isSeriesMergeEligible(series: Series): boolean {
  return canMergeSeries(series);
}
