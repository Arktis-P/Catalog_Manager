import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AppSettings } from "../types";

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [maxConcurrent, setMaxConcurrent] = useState(2);
  const [naiaBaseUrl, setNaiaBaseUrl] = useState("http://127.0.0.1:7243");
  const [naiaPortableDir, setNaiaPortableDir] = useState("");
  const [imagesPerCharacter, setImagesPerCharacter] = useState(2);
  const [promptPrefix, setPromptPrefix] = useState("");
  const [promptSuffix, setPromptSuffix] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
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
        setPromptPrefix(response.generation_prompt_prefix);
        setPromptSuffix(response.generation_prompt_suffix);
        setNegativePrompt(response.generation_negative_prompt);
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
        generation_prompt_prefix: promptPrefix,
        generation_prompt_suffix: promptSuffix,
        generation_negative_prompt: negativePrompt,
      });
      setSettings(response);
      setMaxConcurrent(response.danbooru_collect_max_concurrent);
      setNaiaBaseUrl(response.naia_base_url);
      setNaiaPortableDir(response.naia_portable_dir);
      setImagesPerCharacter(response.generation_images_per_character);
      setPromptPrefix(response.generation_prompt_prefix);
      setPromptSuffix(response.generation_prompt_suffix);
      setNegativePrompt(response.generation_negative_prompt);
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
            Danbooru 작업 큐, NAIA 연결, 이미지 생성 프롬프트 템플릿을 설정합니다.
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
              <p className="field-help">
                기본 2장 권장. 손가락·디테일 문제로 부적절한 이미지가 있을 때 리뷰에서 대체할 수
                있습니다.
              </p>
            </div>

            <div className="field full-width">
              <label htmlFor="prompt-prefix">생성 프롬프트 — 와일드카드 앞 (prefix)</label>
              <textarea
                id="prompt-prefix"
                className="generation-prompt-textarea"
                rows={5}
                value={promptPrefix}
                onChange={(event) => setPromptPrefix(event.target.value)}
              />
              <p className="field-help">
                캐릭터 와일드카드 앞에 붙습니다. <code>{"{gender}"}</code> 플레이스홀더 사용 가능.
              </p>
            </div>

            <div className="field full-width">
              <label htmlFor="prompt-suffix">생성 프롬프트 — 와일드카드 뒤 (suffix)</label>
              <textarea
                id="prompt-suffix"
                className="generation-prompt-textarea"
                rows={3}
                value={promptSuffix}
                onChange={(event) => setPromptSuffix(event.target.value)}
              />
              <p className="field-help">
                캐릭터 와일드카드 뒤에 붙습니다. <code>{"{portrait}"}</code> 플레이스홀더 사용 가능.
              </p>
            </div>

            <div className="field full-width">
              <label htmlFor="negative-prompt">Negative prompt</label>
              <textarea
                id="negative-prompt"
                className="generation-prompt-textarea"
                rows={3}
                value={negativePrompt}
                onChange={(event) => setNegativePrompt(event.target.value)}
              />
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
