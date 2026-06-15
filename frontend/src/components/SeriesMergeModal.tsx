import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Series, SeriesMergeCandidate, SeriesMergePreview } from "../types";

type MergeMode = "into_parent" | "absorb_child";

interface SeriesMergeModalProps {
  series: Series;
  onClose: () => void;
  onMerged: () => void;
}

function canMergeSeries(series: Series): boolean {
  return !series.is_merged_child && (series.status === "collected" || series.status === "tagged");
}

export function SeriesMergeModal({ series, onClose, onMerged }: SeriesMergeModalProps) {
  const [mode, setMode] = useState<MergeMode>("into_parent");
  const [search, setSearch] = useState("");
  const [candidates, setCandidates] = useState<SeriesMergeCandidate[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [preview, setPreview] = useState<SeriesMergePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [mergeProgress, setMergeProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const selectedCandidate = useMemo(
    () => candidates.find((item) => item.id === selectedId) ?? null,
    [candidates, selectedId],
  );

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.listSeriesMergeCandidates(series.id, {
          mode: mode === "into_parent" ? "parent" : "child",
          search: search || undefined,
        });
        if (cancelled) return;
        setCandidates(response.items);
        setSelectedId((current) => {
          if (current && response.items.some((item) => item.id === current)) {
            return current;
          }
          return response.items[0]?.id ?? null;
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
  }, [series.id, mode, search]);

  useEffect(() => {
    if (!selectedId) {
      setPreview(null);
      return;
    }
    const childId = mode === "into_parent" ? series.id : selectedId;
    const parentId = mode === "into_parent" ? selectedId : series.id;
    let cancelled = false;
    const loadPreview = async () => {
      try {
        const result = await api.previewSeriesMerge(childId, parentId);
        if (!cancelled) {
          setPreview(result);
        }
      } catch (err) {
        if (!cancelled) {
          setPreview(null);
          setError(err instanceof Error ? err.message : "Failed to preview merge");
        }
      }
    };
    void loadPreview();
    return () => {
      cancelled = true;
    };
  }, [selectedId, mode, series.id]);

  useEffect(() => {
    if (!submitting) {
      setMergeProgress(0);
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
    if (!selectedId) return;
    setSubmitting(true);
    setMergeProgress(8);
    setError(null);
    try {
      const childId = mode === "into_parent" ? series.id : selectedId;
      const parentId = mode === "into_parent" ? selectedId : series.id;
      await api.mergeSeries(childId, parentId);
      setMergeProgress(100);
      onMerged();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to merge series");
    } finally {
      setSubmitting(false);
    }
  };

  if (!canMergeSeries(series)) {
    return null;
  }

  return (
    <div className="modal-backdrop" onClick={handleClose}>
      <div className="modal modal-wide" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header-row">
          <div>
            <h2 className="modal-title">Merge Series — {series.series_tag}</h2>
            <p className="catalog-card-subtitle">
              collected/tagged 시리즈끼리 병합합니다. 중복 캐릭터는 상위 시리즈 쪽을 유지합니다.
            </p>
          </div>
          <button className="btn btn-small" type="button" disabled={submitting} onClick={handleClose}>
            Close
          </button>
        </div>

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

        <div className="toolbar" style={{ marginBottom: 12 }}>
          <div className="field full-width">
            <label htmlFor="merge-search">
              {mode === "into_parent" ? "상위 시리즈 검색" : "하위 시리즈 검색"}
            </label>
            <input
              id="merge-search"
              value={search}
              disabled={submitting}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="series tag / display name"
            />
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {loading ? <div className="empty-state">Loading candidates...</div> : null}

        {!loading ? (
          <div className="field full-width">
            <label htmlFor="merge-target">대상 시리즈</label>
            <select
              id="merge-target"
              value={selectedId ?? ""}
              disabled={submitting}
              onChange={(event) => setSelectedId(Number(event.target.value))}
            >
              {candidates.length === 0 ? <option value="">No candidates found</option> : null}
              {candidates.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.series_tag}
                  {candidate.display_name ? ` (${candidate.display_name})` : ""}
                  {` · ${candidate.character_count} chars`}
                  {candidate.similarity_score > 0
                    ? ` · match ${Math.round(candidate.similarity_score * 100)}%`
                    : ""}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {preview ? (
          <div className="merge-preview-panel">
            <div>
              <strong>Preview</strong>
            </div>
            <div className="catalog-card-subtitle">
              Child: {preview.child_series_tag} ({preview.child_character_count} characters)
            </div>
            <div className="catalog-card-subtitle">
              Parent: {preview.parent_series_tag}
            </div>
            <div>
              이동 {preview.moved_count.toLocaleString()} · 중복 제외 {preview.duplicate_count.toLocaleString()}
            </div>
          </div>
        ) : null}

        {selectedCandidate ? (
          <div className="catalog-card-subtitle" style={{ marginTop: 8 }}>
            선택: {selectedCandidate.series_tag} · status {selectedCandidate.status}
          </div>
        ) : null}

        <div className="modal-actions merge-modal-actions">
          <div className="merge-progress-area">
            {submitting ? (
              <>
                <div className="merge-progress-label">
                  병합 중…
                  {preview
                    ? ` ${preview.child_series_tag} → ${preview.parent_series_tag} (이동 ${preview.moved_count.toLocaleString()}명)`
                    : ""}
                </div>
                <div className="merge-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(mergeProgress)}>
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
              disabled={!selectedId || !preview || submitting}
              onClick={() => void handleSubmit()}
            >
              {submitting ? "Merging..." : "Merge"}
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
