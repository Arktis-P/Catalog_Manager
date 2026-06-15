import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AppSettings } from "../types";

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [maxConcurrent, setMaxConcurrent] = useState(2);
  const [naiaBaseUrl, setNaiaBaseUrl] = useState("http://127.0.0.1:7243");
  const [naiaPortableDir, setNaiaPortableDir] = useState("");
  const [imagesPerCharacter, setImagesPerCharacter] = useState(1);
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
        setNaiaBaseUrl(response.naia_base_url);
        setNaiaPortableDir(response.naia_portable_dir);
        setImagesPerCharacter(response.generation_images_per_character);
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
        naia_base_url: naiaBaseUrl,
        naia_portable_dir: naiaPortableDir,
        generation_images_per_character: imagesPerCharacter,
      });
      setSettings(response);
      setMaxConcurrent(response.danbooru_collect_max_concurrent);
      setNaiaBaseUrl(response.naia_base_url);
      setNaiaPortableDir(response.naia_portable_dir);
      setImagesPerCharacter(response.generation_images_per_character);
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
            Danbooru 작업 큐와 NAIA 연결 경로를 설정합니다.
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

            <div className="field full-width">
              <label htmlFor="naia-base-url">NAIA API URL</label>
              <input
                id="naia-base-url"
                value={naiaBaseUrl}
                onChange={(event) => setNaiaBaseUrl(event.target.value)}
              />
            </div>

            <div className="field full-width">
              <label htmlFor="naia-portable-dir">NAIA Portable 경로</label>
              <input
                id="naia-portable-dir"
                value={naiaPortableDir}
                onChange={(event) => setNaiaPortableDir(event.target.value)}
              />
            </div>

            <div className="field full-width">
              <label htmlFor="images-per-character">캐릭터당 생성 이미지 수</label>
              <div className="settings-range-row">
                <input
                  id="images-per-character"
                  type="range"
                  min={1}
                  max={4}
                  step={1}
                  value={imagesPerCharacter}
                  onChange={(event) => setImagesPerCharacter(Number(event.target.value))}
                />
                <strong>{imagesPerCharacter}</strong>
              </div>
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
