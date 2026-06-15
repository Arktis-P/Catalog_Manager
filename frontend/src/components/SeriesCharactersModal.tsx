import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CharacterDetail, Series } from "../types";

const PAGE_SIZE = 100;

function formatCollectSources(character: CharacterDetail): string {
  const parts: string[] = [];
  if (character.from_wiki) parts.push("wiki");
  if (character.from_list_page) parts.push("list");
  if (character.from_posts) parts.push("posts");
  if (character.from_related) parts.push("related");
  return parts.length > 0 ? parts.join(", ") : "-";
}

function displayValue(value: string | null | undefined): string {
  return value && value.trim() ? value : "-";
}

function formatGender(value: string | null | undefined): string {
  if (!value) return "-";
  if (value === "no_humans") return "no humans";
  return value;
}

interface SeriesCharactersModalProps {
  series: Series;
  onClose: () => void;
}

export function SeriesCharactersModal({ series, onClose }: SeriesCharactersModalProps) {
  const [items, setItems] = useState<CharacterDetail[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "needs_check">("");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const pageCount = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);

  useEffect(() => {
    setPage(0);
  }, [search, statusFilter, series.id]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.listSeriesCharacters(series.id, {
          search: search || undefined,
          status: statusFilter || undefined,
          skip: page * PAGE_SIZE,
          limit: PAGE_SIZE,
        });
        if (cancelled) return;
        setItems(response.items);
        setTotal(response.total);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load characters");
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
  }, [series.id, search, statusFilter, page]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide modal-characters" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header-row">
          <div>
            <h2 className="modal-title">Characters — {series.series_tag}</h2>
            <p className="catalog-card-subtitle">
              {series.display_name || series.series_tag} · {total.toLocaleString()} character
              {total === 1 ? "" : "s"}
            </p>
          </div>
          <div className="card-actions">
            <button className="btn btn-small" type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        <div className="toolbar" style={{ marginBottom: 12 }}>
          <div className="field">
            <label htmlFor="character-search">Search</label>
            <input
              id="character-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="character tag / display name"
            />
          </div>
          <div className="field">
            <label htmlFor="character-status-filter">Status</label>
            <select
              id="character-status-filter"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as "" | "needs_check")}
            >
              <option value="">All</option>
              <option value="needs_check">needs_check only</option>
            </select>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {loading ? <div className="empty-state">Loading characters...</div> : null}

        {!loading ? (
          <div className="modal-body-scroll">
            <table className="data-table character-detail-table">
              <thead>
                <tr>
                  <th className="col-tag">character_tag</th>
                  <th className="col-name">display_name</th>
                  <th className="col-narrow">posts</th>
                  <th className="col-narrow">sources</th>
                  <th className="col-tags">multi_color_hair</th>
                  <th className="col-tags">hair_color</th>
                  <th className="col-tags">hair_shape</th>
                  <th className="col-tags">eye_color</th>
                  <th className="col-tags-wide">feature_tags</th>
                  <th className="col-tags">source_series</th>
                  <th className="col-narrow">gender</th>
                  <th className="col-tags-wide">generation_prompt</th>
                  <th className="col-narrow">appearance</th>
                  <th className="col-narrow">status</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={14} className="empty-state">
                      No characters found.
                    </td>
                  </tr>
                ) : (
                  items.map((character) => (
                    <tr key={character.id}>
                      <td className="col-tag">{character.character_tag}</td>
                      <td className="col-name">{displayValue(character.display_name)}</td>
                      <td className="col-narrow">{character.post_count.toLocaleString()}</td>
                      <td className="col-narrow">{formatCollectSources(character)}</td>
                      <td className="col-tags">{displayValue(character.multi_color_hair)}</td>
                      <td className="col-tags">{displayValue(character.hair_color)}</td>
                      <td className="col-tags">{displayValue(character.hair_shape)}</td>
                      <td className="col-tags">{displayValue(character.eye_color)}</td>
                      <td className="col-tags-wide">{displayValue(character.feature_tags)}</td>
                      <td className="col-tags">{displayValue(character.source_series_tag)}</td>
                      <td className="col-narrow">{formatGender(character.gender)}</td>
                      <td className="col-tags-wide">{displayValue(character.generation_prompt)}</td>
                      <td className="col-narrow">
                        {character.appearance_confirmed ? (
                          <span className="badge badge-success">confirmed</span>
                        ) : character.multi_color_hair ||
                          character.hair_color ||
                          character.hair_shape ||
                          character.eye_color ||
                          character.feature_tags ||
                          character.gender ? (
                          <span className="badge">draft</span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="col-narrow">
                        {character.needs_check_reason ? (
                          <span className="catalog-card-subtitle" title={character.needs_check_reason}>
                            {character.status}
                          </span>
                        ) : (
                          character.status
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : null}

        {!loading && total > PAGE_SIZE ? (
          <div className="pagination-bar">
            <span className="catalog-card-subtitle">
              Page {page + 1} / {pageCount}
            </span>
            <div className="card-actions">
              <button className="btn btn-small" type="button" disabled={page <= 0} onClick={() => setPage((p) => p - 1)}>
                Previous
              </button>
              <button
                className="btn btn-small"
                type="button"
                disabled={page + 1 >= pageCount}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
