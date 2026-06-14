import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AppearanceReviewItem } from "../types";

function formatDraftTags(item: AppearanceReviewItem): string {
  return [
    item.multi_color_hair ? `multi: ${item.multi_color_hair}` : null,
    item.hair_color ? `hair: ${item.hair_color}` : null,
    item.hair_shape ? `style: ${item.hair_shape}` : null,
    item.eye_color ? `eyes: ${item.eye_color}` : null,
    item.feature_tags ? `features: ${item.feature_tags}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function ReviewPage() {
  const [items, setItems] = useState<AppearanceReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);

  const loadReviews = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listAppearanceReviews({
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
  }, [search]);

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

  const copyPrompt = async (prompt: string | null) => {
    if (!prompt) return;
    await navigator.clipboard.writeText(prompt);
  };

  return (
    <section>
      <header className="page-header">
        <div>
          <h1 className="page-title">Review</h1>
          <p className="page-description">
            Appearance 추출 결과를 확인합니다. 확정 전 태그는 Catalog에 표시되지 않습니다.
          </p>
        </div>
      </header>

      <div className="toolbar">
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
                  {items.map((item) => (
                    <tr key={item.id}>
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
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
