import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Series } from "../types";
import { sortSeriesForGeneration } from "../utils/seriesGenerationSort";

interface SeriesSearchSelectProps {
  value: number | "";
  onChange: (seriesId: number | "", series?: Series | null) => void;
  disabled?: boolean;
}

export function SeriesSearchSelect({ value, onChange, disabled = false }: SeriesSearchSelectProps) {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const [seriesList, setSeriesList] = useState<Series[]>([]);
  const [seriesSearch, setSeriesSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedSeries = useMemo(
    () => seriesList.find((series) => series.id === value) ?? null,
    [seriesList, value],
  );

  const sortedSeries = useMemo(() => sortSeriesForGeneration(seriesList), [seriesList]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void (async () => {
        setLoading(true);
        setError(null);
        try {
          const response = await api.listSeries({
            search: seriesSearch.trim() || undefined,
            sort_by: "post_count",
            sort_order: "desc",
            limit: 500,
            hierarchical: false,
          });
          setSeriesList(response.items);
        } catch (err) {
          setError(err instanceof Error ? err.message : "시리즈 목록을 불러오지 못했습니다.");
        } finally {
          setLoading(false);
        }
      })();
    }, seriesSearch.trim() ? 250 : 0);

    return () => window.clearTimeout(timer);
  }, [seriesSearch]);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  const displayValue = open ? seriesSearch : selectedSeries?.series_tag ?? seriesSearch;

  return (
    <div className="series-search-select" ref={rootRef}>
      <input
        id="generation-series"
        className="series-search-input"
        value={displayValue}
        placeholder="시리즈 검색 또는 선택..."
        disabled={disabled}
        onFocus={() => {
          setOpen(true);
          if (selectedSeries) {
            setSeriesSearch(selectedSeries.series_tag);
          }
        }}
        onChange={(event) => {
          setSeriesSearch(event.target.value);
          setOpen(true);
          if (!event.target.value.trim()) {
            onChange("", null);
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setOpen(false);
          }
        }}
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        autoComplete="off"
      />
      {open ? (
        <div className="series-search-dropdown" id={listboxId} role="listbox">
          {loading ? <div className="series-search-empty">불러오는 중...</div> : null}
          {error ? <div className="series-search-empty series-search-error">{error}</div> : null}
          {!loading && !error && sortedSeries.length === 0 ? (
            <div className="series-search-empty">검색 결과가 없습니다.</div>
          ) : null}
          {!loading && !error
            ? sortedSeries.map((series) => (
                <button
                  key={series.id}
                  type="button"
                  className={`series-search-option${
                    value === series.id ? " series-search-option-active" : ""
                  }${
                    series.generation_pipeline_done || series.status === "generated"
                      ? " series-search-option-done"
                      : ""
                  }`}
                  role="option"
                  aria-selected={value === series.id}
                  onClick={() => {
                    onChange(series.id, series);
                    setSeriesSearch(series.series_tag);
                    setOpen(false);
                  }}
                >
                  <span className="series-search-option-main">
                    <strong>{series.series_tag}</strong>
                    <span className="series-search-option-meta">
                      posts {series.post_count.toLocaleString()} · chars {series.character_count}
                    </span>
                  </span>
                  {series.generation_pipeline_done ? (
                    <span className="badge badge-compact badge-success">catalog</span>
                  ) : series.status === "generated" ? (
                    <span className="badge badge-compact badge-success">generated</span>
                  ) : null}
                </button>
              ))
            : null}
        </div>
      ) : null}
      {selectedSeries?.generation_pipeline_done ? (
        <p className="field-help">이 시리즈는 Catalog 리뷰까지 완료되었습니다.</p>
      ) : selectedSeries?.status === "generated" ? (
        <p className="field-help">리뷰용 1차 이미지 생성이 완료된 시리즈입니다.</p>
      ) : null}
    </div>
  );
}
