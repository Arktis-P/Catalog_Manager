import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AppSettings, NotificationMode } from "../types";
import { useNotificationMode } from "../context/NotificationModeContext";
import {
  ensureNotificationPermission,
  getNotificationPermissionStatus,
  type NotificationPermissionStatus,
} from "../utils/notifications";

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [maxConcurrent, setMaxConcurrent] = useState(2);
  const [naiaBaseUrl, setNaiaBaseUrl] = useState("http://127.0.0.1:7243");
  const [naiaPortableDir, setNaiaPortableDir] = useState("");
  const [imagesPerCharacter, setImagesPerCharacter] = useState(2);
  const [promptPrefix, setPromptPrefix] = useState("");
  const [promptSuffix, setPromptSuffix] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [reviewThumbnailSize, setReviewThumbnailSize] = useState(384);
  const [reviewMaxLoadedImages, setReviewMaxLoadedImages] = useState(30);
  const [minCharacterPostCount, setMinCharacterPostCount] = useState(20);
  const [hfToken, setHfToken] = useState("");
  const [hfWdModel, setHfWdModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  const { mode: contextNotificationMode, setMode: setContextNotificationMode } = useNotificationMode();
  const [notificationMode, setNotificationMode] = useState<NotificationMode>(contextNotificationMode);
  const [notifPermission, setNotifPermission] = useState<NotificationPermissionStatus>(() =>
    getNotificationPermissionStatus(),
  );

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
        setReviewThumbnailSize(response.review_thumbnail_size);
        setReviewMaxLoadedImages(response.review_max_loaded_images);
        setMinCharacterPostCount(response.min_character_post_count);
        setHfToken(response.hf_token ?? "");
        setHfWdModel(response.hf_wd_model ?? "");
        if (response.notification_mode) {
          setNotificationMode(response.notification_mode as NotificationMode);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load settings");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    setNotificationMode(contextNotificationMode);
  }, [contextNotificationMode]);

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
        review_thumbnail_size: reviewThumbnailSize,
        review_max_loaded_images: reviewMaxLoadedImages,
        min_character_post_count: minCharacterPostCount,
        hf_token: hfToken,
        hf_wd_model: hfWdModel,
        notification_mode: notificationMode,
      });
      setContextNotificationMode(notificationMode);
      setSettings(response);
      setMaxConcurrent(response.danbooru_collect_max_concurrent);
      setNaiaBaseUrl(response.naia_base_url);
      setNaiaPortableDir(response.naia_portable_dir);
      setImagesPerCharacter(response.generation_images_per_character);
      setPromptPrefix(response.generation_prompt_prefix);
      setPromptSuffix(response.generation_prompt_suffix);
      setNegativePrompt(response.generation_negative_prompt);
      setReviewThumbnailSize(response.review_thumbnail_size);
      setReviewMaxLoadedImages(response.review_max_loaded_images);
      setMinCharacterPostCount(response.min_character_post_count);
      setHfToken(response.hf_token ?? "");
      setHfWdModel(response.hf_wd_model ?? "");
      if (response.notification_mode) {
        setNotificationMode(response.notification_mode as NotificationMode);
      }
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
              <label htmlFor="min-post-count">
                캐릭터 최소 포스트 수 (수집 필터 · 외형 추출 필터 공통)
              </label>
              <div className="settings-range-row">
                <input
                  id="min-post-count"
                  type="number"
                  min={0}
                  max={500}
                  step={5}
                  value={minCharacterPostCount}
                  onChange={(event) => setMinCharacterPostCount(Number(event.target.value))}
                  style={{ width: 80 }}
                />
              </div>
              <p className="field-help">
                이 값은 <strong>시리즈 태그 포함 포스트 수</strong> 기준입니다 (전체 포스트의 약 60~70% 수준).
                임계값 미만 캐릭터는 수집 시 저장하지 않고 외형 추출 시에도 건너뜁니다.
                기본값 10 권장 — 10 미만은 외형 태그 추출 통계가 불안정해집니다. 0으로 설정하면 필터를 해제합니다.
              </p>
            </div>

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
              <label htmlFor="review-thumbnail-size">Review 썸네일 크기 (px)</label>
              <div className="settings-range-row">
                <input
                  id="review-thumbnail-size"
                  type="range"
                  min={128}
                  max={512}
                  step={32}
                  value={reviewThumbnailSize}
                  onChange={(event) => setReviewThumbnailSize(Number(event.target.value))}
                />
                <strong>{reviewThumbnailSize}</strong>
              </div>
              <p className="field-help">
                Catalog Review 슬롯에 로드하는 썸네일 해상도입니다. 낮을수록 메모리 사용이 줄어듭니다.
              </p>
            </div>

            <div className="field full-width">
              <label htmlFor="review-max-loaded-images">Review 동시 로드 이미지 상한</label>
              <div className="settings-range-row">
                <input
                  id="review-max-loaded-images"
                  type="range"
                  min={10}
                  max={80}
                  step={5}
                  value={reviewMaxLoadedImages}
                  onChange={(event) => setReviewMaxLoadedImages(Number(event.target.value))}
                />
                <strong>{reviewMaxLoadedImages}</strong>
              </div>
              <p className="field-help">
                가상 스크롤 뷰포트 주변에서 유지할 이미지 수 상한입니다.
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

            <div className="field full-width">
              <label htmlFor="hf-token">Hugging Face Token (WD 자동 태깅)</label>
              <input
                id="hf-token"
                type="password"
                placeholder="hf_..."
                value={hfToken}
                onChange={(event) => setHfToken(event.target.value)}
              />
              <p className="field-help">
                설정하면 이미지 생성 후 HF Inference API로 WD 태그를 추출해 캐릭터·머리색·눈색·성별을
                자동 검증합니다. 비워두면 선명도 기반 품질 검사만 수행합니다.{" "}
                <a
                  href="https://huggingface.co/settings/tokens"
                  target="_blank"
                  rel="noreferrer"
                >
                  HF 토큰 발급
                </a>
              </p>
            </div>

            <div className="field full-width">
              <label htmlFor="hf-wd-model">HF WD Model ID</label>
              <input
                id="hf-wd-model"
                placeholder="SmilingWolf/wd-eva02-large-tagger-v3"
                value={hfWdModel}
                onChange={(event) => setHfWdModel(event.target.value)}
              />
              <p className="field-help">
                비워두면 기본값 <code>SmilingWolf/wd-eva02-large-tagger-v3</code>를 사용합니다.
              </p>
            </div>

            <div className="field full-width">
              <label>데스크탑 알림</label>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="notification_mode"
                    value="each"
                    checked={notificationMode === "each"}
                    onChange={() => setNotificationMode("each")}
                  />
                  작업 하나가 끝날 때마다 알림
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="notification_mode"
                    value="all_done"
                    checked={notificationMode === "all_done"}
                    onChange={() => setNotificationMode("all_done")}
                  />
                  대기 목록의 모든 작업이 끝났을 때만 알림
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="notification_mode"
                    value="none"
                    checked={notificationMode === "none"}
                    onChange={() => setNotificationMode("none")}
                  />
                  알림 없음
                </label>
              </div>
              <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 12 }}>
                {notifPermission === "granted" && (
                  <span style={{ color: "var(--color-success, #4caf50)", fontSize: 13 }}>
                    알림 권한이 허용되어 있습니다.
                  </span>
                )}
                {notifPermission === "denied" && (
                  <span style={{ color: "var(--color-error, #f44336)", fontSize: 13 }}>
                    알림이 차단되어 있습니다. 브라우저 주소창 옆 자물쇠 아이콘에서 알림을 허용해주세요.
                  </span>
                )}
                {notifPermission === "default" && (
                  <>
                    <span style={{ fontSize: 13 }}>알림 권한이 아직 설정되지 않았습니다.</span>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      style={{ fontSize: 12, padding: "4px 10px" }}
                      onClick={() => {
                        void ensureNotificationPermission().then((granted) => {
                          setNotifPermission(getNotificationPermissionStatus());
                          if (granted) setSavedMessage("알림 권한이 허용되었습니다.");
                        });
                      }}
                    >
                      알림 권한 요청
                    </button>
                  </>
                )}
                {notifPermission === "unsupported" && (
                  <span style={{ color: "var(--color-text-muted, #888)", fontSize: 13 }}>
                    이 브라우저는 데스크탑 알림을 지원하지 않습니다.
                  </span>
                )}
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
