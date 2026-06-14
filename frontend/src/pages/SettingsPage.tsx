import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AppSettings } from "../types";

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [maxConcurrent, setMaxConcurrent] = useState(2);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.getSettings();
        setSettings(response);
        setMaxConcurrent(response.danbooru_collect_max_concurrent);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load settings");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSavedMessage(null);
    try {
      const response = await api.updateSettings({
        danbooru_collect_max_concurrent: maxConcurrent,
      });
      setSettings(response);
      setMaxConcurrent(response.danbooru_collect_max_concurrent);
      setSavedMessage("설정을 저장했습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section>
      <header className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-description">
            Danbooru 작업 큐 설정. 캐릭터 수집과 외형 태그 추출이 같은 큐를 공유합니다.
          </p>
        </div>
      </header>

      {loading ? <div className="empty-state">Loading settings...</div> : null}
      {error ? <div className="error-banner">{error}</div> : null}
      {savedMessage ? <div className="success-banner">{savedMessage}</div> : null}

      {!loading && settings ? (
        <form className="panel" onSubmit={(event) => void handleSubmit(event)}>
          <div className="form-grid">
            <div className="field full-width">
              <label htmlFor="max-concurrent">
                동시 Danbooru 작업 수 (캐릭터 수집 + 외형 추출 공유)
              </label>
              <div className="settings-range-row">
                <input
                  id="max-concurrent"
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={maxConcurrent}
                  onChange={(event) => setMaxConcurrent(Number(event.target.value))}
                />
                <strong>{maxConcurrent}</strong>
              </div>
              <p className="field-help">
                1~5 사이 값. API rate limit을 피하려면 2 이하를 권장합니다. 현재 요청 간격:{" "}
                {settings.danbooru_request_delay}s
              </p>
            </div>
          </div>
          <div className="modal-actions">
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
