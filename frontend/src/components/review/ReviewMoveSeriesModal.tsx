import { useEffect, useState } from "react";
import { SeriesSearchSelect } from "../SeriesSearchSelect";
import type { Series } from "../../types";

interface ReviewMoveSeriesModalProps {
  characterTag: string;
  currentSeriesTag: string;
  onClose: () => void;
  onConfirm: (seriesId: number) => Promise<void>;
}

export function ReviewMoveSeriesModal({
  characterTag,
  currentSeriesTag,
  onClose,
  onConfirm,
}: ReviewMoveSeriesModalProps) {
  const [seriesId, setSeriesId] = useState<number | "">("");
  const [selectedSeries, setSelectedSeries] = useState<Series | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const handleSubmit = async () => {
    if (!seriesId) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onConfirm(seriesId);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "시리즈 이동에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal panel review-move-series-modal" onClick={(event) => event.stopPropagation()}>
        <h2 className="page-title" style={{ fontSize: "1.1rem" }}>
          시리즈 이동
        </h2>
        <p className="catalog-card-subtitle">
          {characterTag} · 현재 {currentSeriesTag}
        </p>
        <div className="field" style={{ marginTop: 16 }}>
          <label>대상 시리즈</label>
          <SeriesSearchSelect
            value={seriesId}
            onChange={(id, series) => {
              setSeriesId(id);
              setSelectedSeries(series ?? null);
            }}
          />
        </div>
        {selectedSeries ? (
          <div className="catalog-card-subtitle" style={{ marginTop: 8 }}>
            → {selectedSeries.series_tag}
          </div>
        ) : null}
        {error ? <div className="error-banner" style={{ marginTop: 12 }}>{error}</div> : null}
        <div className="modal-actions" style={{ marginTop: 16 }}>
          <button className="btn" type="button" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!seriesId || saving}
            onClick={() => void handleSubmit()}
          >
            {saving ? "Moving..." : "Move"}
          </button>
        </div>
      </div>
    </div>
  );
}
