import { Fragment, useEffect, useState } from "react";
import { api } from "../../api/client";
import { SeriesSearchSelect } from "../SeriesSearchSelect";
import type { AppearanceReviewItem, Series } from "../../types";

function formatDraftTags(item: AppearanceReviewItem): string {
  return [
    item.multi_color_hair ? `multi: ${item.multi_color_hair}` : null,
    item.hair_color ? `hair: ${item.hair_color}` : null,
    item.hair_shape ? `style: ${item.hair_shape}` : null,
    item.eye_color ? `eyes: ${item.eye_color}` : null,
    item.gender ? `gender: ${item.gender}` : null,
    item.feature_tags ? `features: ${item.feature_tags}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

interface DraftFields {
  multi_color_hair: string;
  hair_color: string;
  hair_shape: string;
  eye_color: string;
  feature_tags: string;
  gender: string;
}

function toDraft(item: AppearanceReviewItem): DraftFields {
  return {
    multi_color_hair: item.multi_color_hair ?? "",
    hair_color: item.hair_color ?? "",
    hair_shape: item.hair_shape ?? "",
    eye_color: item.eye_color ?? "",
    feature_tags: item.feature_tags ?? "",
    gender: item.gender ?? "",
  };
}

export function AppearanceReviewPanel() {
  const [items, setItems] = useState<AppearanceReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | "">("");
  const [selectedSeries, setSelectedSeries] = useState<Series | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, DraftFields>>({});
  const [savingId, setSavingId] = useState<number | null>(null);

  const loadReviews = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listAppearanceReviews({
        series_tag: selectedSeries?.series_tag,
        search: search || undefined,
        limit: 100,
      });
      setItems(response.items);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load appearance reviews");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadReviews();
  }, [search, selectedSeries?.series_tag]);

  const handleConfirm = async (item: AppearanceReviewItem) => {
    setConfirmingId(item.id);
    setError(null);
    try {
      await api.confirmAppearanceReview(item.id);
      await loadReviews();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to confirm appearance tags");
    } finally {
      setConfirmingId(null);
    }
  };

  const handleSaveDraft = async (item: AppearanceReviewItem) => {
    const draft = drafts[item.id] ?? toDraft(item);
    setSavingId(item.id);
    setError(null);
    try {
      const updated = await api.updateAppearanceReview(item.id, {
        multi_color_hair: draft.multi_color_hair || null,
        hair_color: draft.hair_color || null,
        hair_shape: draft.hair_shape || null,
        eye_color: draft.eye_color || null,
        feature_tags: draft.feature_tags || null,
        gender: draft.gender || null,
      });
      setItems((current) => current.map((entry) => (entry.id === item.id ? updated : entry)));
      setEditingId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save appearance tags");
    } finally {
      setSavingId(null);
    }
  };

  const copyPrompt = async (prompt: string | null) => {
    if (!prompt) return;
    await navigator.clipboard.writeText(prompt);
  };

  return (
    <>
      <div className="toolbar">
        <div className="field review-series-field">
          <label>Series</label>
          <SeriesSearchSelect
            value={selectedSeriesId}
            onChange={(seriesId, series) => {
              setSelectedSeriesId(seriesId);
              setSelectedSeries(series ?? null);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="review-search">Search</label>
          <input
            id="review-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="character / series"
          />
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadReviews()}>
            Refresh
          </button>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {loading ? <div className="empty-state">Loading appearance reviews...</div> : null}

      {!loading ? (
        <>
          <div className="catalog-card-subtitle" style={{ marginBottom: 12 }}>
            Pending appearance review: {total.toLocaleString()}
          </div>
          {items.length === 0 ? (
            <div className="empty-state panel">확인할 외형 태그가 없습니다.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>character</th>
                    <th>series</th>
                    <th>draft tags</th>
                    <th>generation prompt</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const editing = editingId === item.id;
                    const draft = drafts[item.id] ?? toDraft(item);
                    return (
                      <Fragment key={item.id}>
                        <tr>
                          <td className="cell-ellipsis" title={item.character_tag}>
                            {item.character_tag}
                          </td>
                          <td className="cell-ellipsis" title={item.series_tag}>
                            {item.series_tag}
                          </td>
                          <td className="cell-ellipsis" title={formatDraftTags(item)}>
                            {formatDraftTags(item) || "-"}
                          </td>
                          <td className="cell-ellipsis" title={item.generation_prompt || undefined}>
                            {item.generation_prompt || "-"}
                          </td>
                          <td>
                            <div className="table-actions">
                              <button
                                className="btn btn-small"
                                type="button"
                                onClick={() => {
                                  setEditingId(editing ? null : item.id);
                                  setDrafts((current) => ({ ...current, [item.id]: toDraft(item) }));
                                }}
                              >
                                {editing ? "Close" : "Edit"}
                              </button>
                              <button
                                className="btn btn-small"
                                type="button"
                                disabled={!item.generation_prompt}
                                onClick={() => void copyPrompt(item.generation_prompt)}
                              >
                                Copy Prompt
                              </button>
                              <button
                                className="btn btn-small btn-primary"
                                type="button"
                                disabled={confirmingId === item.id}
                                onClick={() => void handleConfirm(item)}
                              >
                                {confirmingId === item.id ? "Confirming..." : "Confirm"}
                              </button>
                              {item.danbooru_url ? (
                                <a
                                  className="btn btn-small"
                                  href={item.danbooru_url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  Danbooru
                                </a>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                        {editing ? (
                          <tr key={`${item.id}-edit`}>
                            <td colSpan={5}>
                              <div className="appearance-edit-grid">
                                <label>
                                  hair_color
                                  <input
                                    value={draft.hair_color}
                                    onChange={(event) =>
                                      setDrafts((current) => ({
                                        ...current,
                                        [item.id]: { ...draft, hair_color: event.target.value },
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  multi_color_hair
                                  <input
                                    value={draft.multi_color_hair}
                                    onChange={(event) =>
                                      setDrafts((current) => ({
                                        ...current,
                                        [item.id]: { ...draft, multi_color_hair: event.target.value },
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  hair_shape
                                  <input
                                    value={draft.hair_shape}
                                    onChange={(event) =>
                                      setDrafts((current) => ({
                                        ...current,
                                        [item.id]: { ...draft, hair_shape: event.target.value },
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  eye_color
                                  <input
                                    value={draft.eye_color}
                                    onChange={(event) =>
                                      setDrafts((current) => ({
                                        ...current,
                                        [item.id]: { ...draft, eye_color: event.target.value },
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  feature_tags
                                  <input
                                    value={draft.feature_tags}
                                    onChange={(event) =>
                                      setDrafts((current) => ({
                                        ...current,
                                        [item.id]: { ...draft, feature_tags: event.target.value },
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  gender
                                  <input
                                    value={draft.gender}
                                    onChange={(event) =>
                                      setDrafts((current) => ({
                                        ...current,
                                        [item.id]: { ...draft, gender: event.target.value },
                                      }))
                                    }
                                  />
                                </label>
                              </div>
                              <div className="table-actions" style={{ marginTop: 10 }}>
                                <button
                                  className="btn btn-small btn-primary"
                                  type="button"
                                  disabled={savingId === item.id}
                                  onClick={() => void handleSaveDraft(item)}
                                >
                                  {savingId === item.id ? "Saving..." : "Save tags"}
                                </button>
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </>
  );
}
