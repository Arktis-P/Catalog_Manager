import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  AppSettings,
  NotificationDisplay,
  NotificationMode,
  PendingImageRecheckJob,
  PendingImageRecheckPreview,
  WdTaggerModelStatus,
} from "../types";
import { useNotificationMode } from "../context/NotificationModeContext";
import {
  ensureNotificationPermission,
  getNotificationPermissionStatus,
  type NotificationPermissionStatus,
} from "../utils/notifications";
import {
  getV2ReviewCardSize,
  getV2ReviewCardWidthPx,
  setV2ReviewCardSize,
  setV2ReviewCardWidthPx,
  type V2ReviewCardSize,
} from "../utils/v2ReviewCardSettings";

// ── Pending 이미지 재검사 진단 코드 ──────────────────────────────────────────
// identity_reasons / errors에 담기는 값은 백엔드가 고정 문자열(코드)로만 채운다
// (app/services/identity_checker.py, app/integrations/image_tagger/hf_wd_tagger.py).
// 여기 목록에 없는 문자열은 원문을 절대 노출하지 않고 "알 수 없는 오류"로 묶는다 —
// 토큰/URL 등 민감정보가 섞인 예외 메시지가 그대로 렌더링되는 것을 막기 위함이다.
type RecheckReasonCategory =
  | "token"
  | "permission"
  | "model"
  | "endpoint"
  | "network"
  | "content"
  | "file"
  | "unknown";

interface RecheckReasonInfo {
  label: string;
  category: RecheckReasonCategory;
  detail?: string;
}

const RECHECK_REASON_INFO: Record<string, RecheckReasonInfo> = {
  tagger_auth_error: {
    label: "토큰 인증 오류",
    category: "token",
    detail:
      "토큰이 없거나 만료·폐기되었습니다. 이전 버전에서는 Inference Providers 권한 부족(HTTP 403)도 이 코드로 저장됐으므로, 기존 800건은 토큰의 Make calls to Inference Providers 권한도 함께 확인하세요.",
  },
  tagger_token_permission: {
    label: "Inference Providers 권한 없음",
    category: "permission",
    detail:
      "토큰 유효성과 별개로 Inference Providers 권한이 없습니다. Hugging Face 토큰 설정에서 Inference Providers 접근 권한을 추가한 뒤 다시 시도하세요.",
  },
  tagger_model_not_found: {
    label: "모델/엔드포인트를 찾을 수 없음",
    category: "model",
    detail: "설정된 경로에서 모델 또는 엔드포인트를 찾을 수 없습니다. 모델 ID나 엔드포인트 URL을 다시 확인하세요.",
  },
  tagger_model_unavailable: {
    label: "모델 미배포 (사용 불가)",
    category: "model",
    detail:
      "선택한 모델이 이 추론 제공자에는 배포되어 있지 않습니다. 다른 모델을 선택하거나 전용(dedicated) Hugging Face Inference Endpoint를 구성한 뒤 다시 시도하세요.",
  },
  tagger_service_unavailable: {
    label: "서비스 사용 불가 (전용 엔드포인트 필요 가능)",
    category: "endpoint",
    detail:
      "레거시 엔드포인트가 제거되었거나 서비스가 응답하지 않습니다. 라우터 또는 전용(dedicated) 엔드포인트 설정을 확인하세요.",
  },
  tagger_rate_limited: {
    label: "요청 한도 초과",
    category: "network",
    detail: "잠시 후 다시 시도하거나 전용 엔드포인트 사용을 고려하세요.",
  },
  tagger_timeout: {
    label: "응답 시간 초과",
    category: "network",
    detail: "네트워크 상태 또는 엔드포인트 응답 속도를 확인하세요.",
  },
  tagger_invalid_response: {
    label: "잘못된 응답 형식",
    category: "network",
    detail: "엔드포인트 설정(모델 경로 등)을 확인하세요.",
  },
  tagger_error: {
    label: "태거 오류",
    category: "unknown",
    detail: "원인이 명확하지 않은 태거 호출 오류입니다.",
  },
  image_file_missing: {
    label: "이미지 파일 누락",
    category: "file",
    detail: "원본 이미지 파일을 찾을 수 없어 이 이미지는 건너뛰었습니다.",
  },
  character_tag_undetected: {
    label: "캐릭터 태그 미검출",
    category: "content",
    detail: "이미지에서 해당 캐릭터 특징이 검출되지 않았습니다.",
  },
  boy_character_tag_undetected: {
    label: "캐릭터 태그 미검출 (남성)",
    category: "content",
  },
  character_tag_low_confidence: {
    label: "캐릭터 태그 신뢰도 낮음",
    category: "content",
  },
  hair_color_mismatch: {
    label: "머리색 불일치",
    category: "content",
  },
  unexpected_multicolor_tag: {
    label: "예상치 못한 멀티컬러 태그",
    category: "content",
  },
  character_tag_confident: {
    label: "판정 통과",
    category: "content",
  },
};

const RECHECK_UNKNOWN_REASON_CODE = "unknown_error";
const RECHECK_CONFIG_CATEGORIES = new Set<RecheckReasonCategory>([
  "token",
  "permission",
  "model",
  "endpoint",
  "network",
  "unknown",
]);

function normalizeRecheckReasonCode(value: string): string {
  const trimmed = value.trim().toLowerCase();
  if (!trimmed) return RECHECK_UNKNOWN_REASON_CODE;
  if (RECHECK_REASON_INFO[trimmed]) return trimmed;
  const prefix = trimmed.split(":")[0].trim();
  if (RECHECK_REASON_INFO[prefix]) return prefix;
  return RECHECK_UNKNOWN_REASON_CODE;
}

function extractRecheckReasonFromRecord(record: Record<string, unknown>): { code: string; count: number } {
  const rawCount = record.count;
  const count =
    typeof rawCount === "number" && Number.isFinite(rawCount) && rawCount > 0 ? Math.floor(rawCount) : 1;
  for (const key of ["reason_code", "reason", "code", "error"]) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return { code: normalizeRecheckReasonCode(value), count };
    }
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const nested = extractRecheckReasonFromRecord(value as Record<string, unknown>);
      if (nested.code !== RECHECK_UNKNOWN_REASON_CODE) {
        return { code: nested.code, count };
      }
    }
  }
  return { code: RECHECK_UNKNOWN_REASON_CODE, count: 1 };
}

function bumpRecheckReasonCount(map: Map<string, number>, code: string, amount: number): void {
  map.set(code, (map.get(code) ?? 0) + amount);
}

function collectRecheckReasonCounts(source: unknown): Map<string, number> {
  const counts = new Map<string, number>();
  const visit = (value: unknown) => {
    if (value === null || value === undefined) return;
    if (typeof value === "string") {
      bumpRecheckReasonCount(counts, normalizeRecheckReasonCode(value), 1);
      return;
    }
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (typeof value === "object") {
      const { code, count } = extractRecheckReasonFromRecord(value as Record<string, unknown>);
      bumpRecheckReasonCount(counts, code, count);
      return;
    }
  };
  visit(source);
  return counts;
}

interface RecheckReasonBreakdownEntry {
  code: string;
  count: number;
  label: string;
  category: RecheckReasonCategory;
  detail?: string;
}

function toRecheckReasonBreakdown(counts: Map<string, number>): RecheckReasonBreakdownEntry[] {
  return Array.from(counts.entries())
    .map(([code, count]) => {
      const info = RECHECK_REASON_INFO[code];
      return {
        code,
        count,
        label: info?.label ?? "알 수 없는 오류",
        category: info?.category ?? "unknown",
        detail: info?.detail,
      };
    })
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "ko"));
}

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
  const [v2CardSize, setV2CardSize] = useState<V2ReviewCardSize>("medium");
  const [v2CardWidthPx, setV2CardWidthPx] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  const {
    mode: contextNotificationMode,
    setMode: setContextNotificationMode,
    display: contextNotificationDisplay,
    setDisplay: setContextNotificationDisplay,
  } = useNotificationMode();
  const [notificationMode, setNotificationMode] = useState<NotificationMode>(contextNotificationMode);
  const [notificationDisplay, setNotificationDisplay] = useState<NotificationDisplay>(contextNotificationDisplay);
  const [notifPermission, setNotifPermission] = useState<NotificationPermissionStatus>(() =>
    getNotificationPermissionStatus(),
  );

  const [recheckBatchSize, setRecheckBatchSize] = useState(200);
  const [recheckTaggerFailuresOnly, setRecheckTaggerFailuresOnly] = useState(true);
  const [recheckPreview, setRecheckPreview] = useState<PendingImageRecheckPreview | null>(null);
  const [recheckPreviewLoading, setRecheckPreviewLoading] = useState(false);
  const [recheckPreviewError, setRecheckPreviewError] = useState<string | null>(null);
  const [recheckJob, setRecheckJob] = useState<PendingImageRecheckJob | null>(null);
  const [recheckStarting, setRecheckStarting] = useState(false);
  const [recheckActionError, setRecheckActionError] = useState<string | null>(null);

  const [wdModelStatus, setWdModelStatus] = useState<WdTaggerModelStatus | null>(null);
  const [wdModelLoading, setWdModelLoading] = useState(true);
  const [wdModelActionError, setWdModelActionError] = useState<string | null>(null);
  const [wdModelStarting, setWdModelStarting] = useState(false);
  const [wdModelCancelling, setWdModelCancelling] = useState(false);

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
        setV2CardSize(getV2ReviewCardSize() ?? (response.v2_review_card_size as V2ReviewCardSize) ?? "medium");
        setV2CardWidthPx(getV2ReviewCardWidthPx() ?? response.v2_review_card_width_px ?? 0);
        if (response.notification_mode) {
          setNotificationMode(response.notification_mode as NotificationMode);
        }
        if (response.notification_display) {
          setNotificationDisplay(response.notification_display as NotificationDisplay);
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

  useEffect(() => {
    setNotificationDisplay(contextNotificationDisplay);
  }, [contextNotificationDisplay]);

  const handleCardSizeChange = (size: V2ReviewCardSize) => {
    setV2CardSize(size);
    setV2ReviewCardSize(size);
  };

  const handleCardWidthChange = (px: number) => {
    setV2CardWidthPx(px);
    setV2ReviewCardWidthPx(px);
  };

  const isRecheckActive = recheckJob?.status === "queued" || recheckJob?.status === "running";

  const loadRecheckPreview = async (batchSize: number, taggerFailuresOnly = recheckTaggerFailuresOnly) => {
    setRecheckPreviewLoading(true);
    setRecheckPreviewError(null);
    try {
      const preview = await api.previewPendingImageRecheck(batchSize, taggerFailuresOnly);
      setRecheckPreview(preview);
    } catch (err) {
      setRecheckPreviewError(err instanceof Error ? err.message : "미리보기를 불러오지 못했습니다");
    } finally {
      setRecheckPreviewLoading(false);
    }
  };

  useEffect(() => {
    void loadRecheckPreview(recheckBatchSize);
    void (async () => {
      try {
        const job = await api.getPendingImageRecheckStatus();
        setRecheckJob(job);
      } catch {
        // 이전에 실행한 재검사 작업이 없으면 404가 발생합니다 — 무시합니다.
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadWdModelStatus = async () => {
    try {
      const status = await api.getWdTaggerModelStatus();
      setWdModelStatus(status);
      return status;
    } catch (err) {
      setWdModelActionError(err instanceof Error ? err.message : "모델 상태를 가져오지 못했습니다");
      return null;
    }
  };

  useEffect(() => {
    void (async () => {
      setWdModelLoading(true);
      await loadWdModelStatus();
      setWdModelLoading(false);
    })();
  }, []);

  useEffect(() => {
    if (!wdModelStatus?.downloading) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadWdModelStatus();
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wdModelStatus?.downloading]);

  const handleStartWdModelDownload = async () => {
    setWdModelStarting(true);
    setWdModelActionError(null);
    try {
      const status = await api.startWdTaggerModelDownload();
      setWdModelStatus(status);
    } catch (err) {
      setWdModelActionError(err instanceof Error ? err.message : "모델 다운로드를 시작하지 못했습니다");
    } finally {
      setWdModelStarting(false);
    }
  };

  const handleCancelWdModelDownload = async () => {
    setWdModelCancelling(true);
    setWdModelActionError(null);
    try {
      const status = await api.cancelWdTaggerModelDownload();
      setWdModelStatus(status);
    } catch (err) {
      setWdModelActionError(err instanceof Error ? err.message : "모델 다운로드를 취소하지 못했습니다");
    } finally {
      setWdModelCancelling(false);
    }
  };

  const wdModelInstalled = wdModelStatus?.installed ?? false;

  const formatBytes = (bytes: number): string => {
    if (bytes <= 0) return "0 MB";
    const mb = bytes / (1024 * 1024);
    if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
    return `${mb.toFixed(1)} MB`;
  };

  const wdModelPercent =
    wdModelStatus && wdModelStatus.total_bytes && wdModelStatus.total_bytes > 0
      ? Math.min(100, Math.round((wdModelStatus.bytes_downloaded / wdModelStatus.total_bytes) * 100))
      : null;

  useEffect(() => {
    if (!recheckJob || (recheckJob.status !== "queued" && recheckJob.status !== "running")) {
      return;
    }
    const jobId = recheckJob.job_id;
    const poll = async () => {
      try {
        const updated = await api.getPendingImageRecheckJob(jobId);
        setRecheckJob(updated);
        if (updated.status !== "queued" && updated.status !== "running") {
          void loadRecheckPreview(recheckBatchSize);
        }
      } catch (err) {
        setRecheckActionError(err instanceof Error ? err.message : "작업 상태를 가져오지 못했습니다");
      }
    };
    const timer = window.setInterval(() => {
      void poll();
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recheckJob?.job_id, recheckJob?.status]);

  const handleStartRecheck = async () => {
    if (!wdModelInstalled) {
      setRecheckActionError(
        "로컬 WD 모델이 설치되어 있지 않습니다. 위의 'WD 태거 모델' 섹션에서 모델을 먼저 다운로드한 뒤 재검사를 시작하세요.",
      );
      return;
    }
    const target = recheckPreview?.eligible_images ?? 0;
    if (
      !window.confirm(
        `대상 이미지 ${target.toLocaleString()}장의 정체성을 재검사합니다` +
          (recheckTaggerFailuresOnly ? " (태거 실패분만)." : ".") +
          " 리뷰 완료 항목은 제외되며, 태그·외형 정보는 변경하지 않고 정체성 판정만 다시 계산합니다. 계속할까요?",
      )
    ) {
      return;
    }
    setRecheckStarting(true);
    setRecheckActionError(null);
    try {
      const job = await api.startPendingImageRecheck(recheckBatchSize, recheckTaggerFailuresOnly);
      setRecheckJob(job);
    } catch (err) {
      setRecheckActionError(err instanceof Error ? err.message : "재검사를 시작하지 못했습니다");
    } finally {
      setRecheckStarting(false);
    }
  };

  const handleCancelRecheck = async () => {
    if (!recheckJob) return;
    if (!window.confirm("실행 중인 재검사를 취소할까요?")) return;
    setRecheckActionError(null);
    try {
      const job = await api.cancelPendingImageRecheckJob(recheckJob.job_id);
      setRecheckJob(job);
    } catch (err) {
      setRecheckActionError(err instanceof Error ? err.message : "재검사를 취소하지 못했습니다");
    }
  };

  const recheckPercent =
    recheckJob && recheckJob.total > 0
      ? Math.min(100, Math.round((recheckJob.current / recheckJob.total) * 100))
      : null;

  const recheckStatusLabels: Record<string, string> = {
    queued: "대기 중",
    running: "진행 중",
    completed: "완료",
    cancelled: "취소됨",
    failed: "실패",
  };

  const identityStatusLabels: Record<string, string> = {
    pass: "성공",
    warning: "경고",
    reject: "거부",
  };

  // job.identity_reasons는 최근 처리된 이미지의 판정 사유(문자열 배열)만 담고,
  // job.errors는 이미지별 오류 레코드를 누적한다. 둘 다 방어적으로 파싱해
  // 코드별 건수로 집계한다 — 백엔드가 향후 누적/카운트 필드를 추가해도 그대로 동작한다.
  const recheckIdentityReasonBreakdown = useMemo(
    () => toRecheckReasonBreakdown(collectRecheckReasonCounts(recheckJob?.identity_reasons ?? [])),
    [recheckJob?.identity_reasons],
  );
  const recheckErrorBreakdown = useMemo(
    () => toRecheckReasonBreakdown(collectRecheckReasonCounts(recheckJob?.errors ?? [])),
    [recheckJob?.errors],
  );
  const recheckHasConfigIssue = [...recheckIdentityReasonBreakdown, ...recheckErrorBreakdown].some(
    (entry) => RECHECK_CONFIG_CATEGORIES.has(entry.category) && RECHECK_REASON_INFO[entry.code],
  );
  const recheckPrimaryIssue =
    [...recheckIdentityReasonBreakdown, ...recheckErrorBreakdown]
      .filter((entry) => RECHECK_CONFIG_CATEGORIES.has(entry.category) && RECHECK_REASON_INFO[entry.code])
      .sort((a, b) => b.count - a.count)[0] ?? null;

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
        notification_display: notificationDisplay,
        v2_review_card_size: v2CardSize,
        v2_review_card_width_px: v2CardWidthPx,
      });
      setContextNotificationMode(notificationMode);
      setContextNotificationDisplay(notificationDisplay);
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
      if (response.notification_display) {
        setNotificationDisplay(response.notification_display as NotificationDisplay);
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
              <label>V2 리뷰 카드 크기</label>
              <div style={{ display: "flex", gap: 8 }}>
                {(["small", "medium", "large"] as const).map((size) => (
                  <button
                    key={size}
                    type="button"
                    className={`btn btn-small${v2CardSize === size ? " btn-primary" : ""}`}
                    onClick={() => handleCardSizeChange(size)}
                  >
                    {size === "small" ? "작게" : size === "medium" ? "보통" : "크게"}
                  </button>
                ))}
              </div>
              <div className="settings-range-row" style={{ marginTop: 8 }}>
                <label htmlFor="v2-card-width-px" style={{ whiteSpace: "nowrap" }}>
                  사용자 지정 너비 (px, 0 = 사전 설정 사용)
                </label>
                <input
                  id="v2-card-width-px"
                  type="number"
                  min={0}
                  max={1200}
                  step={10}
                  value={v2CardWidthPx}
                  onChange={(event) => handleCardWidthChange(Number(event.target.value))}
                  style={{ width: 90 }}
                />
              </div>
              <p className="field-help">
                V2 Review 카드 그리드에 즉시 반영됩니다. 이 값은 브라우저에 저장되며 Save 버튼과 무관하게 바로 적용됩니다.
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
              <label htmlFor="hf-token">Hugging Face Token (선택)</label>
              <input
                id="hf-token"
                type="password"
                placeholder="hf_..."
                value={hfToken}
                onChange={(event) => setHfToken(event.target.value)}
              />
              <p className="field-help">
                캐릭터 재현(identity) 검사와 Pending 재검사는 로컬 WD ONNX 모델만 사용하며, 이 토큰은
                identity 경로에서 사용하지 않습니다. 다른 HF 연동용으로만 남긴 설정입니다.{" "}
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
              <label htmlFor="hf-wd-model">HF WD Model ID (미사용)</label>
              <input
                id="hf-wd-model"
                placeholder="SmilingWolf/wd-eva02-large-tagger-v3"
                value={hfWdModel}
                onChange={(event) => setHfWdModel(event.target.value)}
              />
              <p className="field-help">
                identity 검사는 아래 <strong>WD 태거 모델 (로컬)</strong>의{" "}
                <code>SmilingWolf/wd-swinv2-tagger-v3</code> ONNX만 사용합니다. HF Inference API /
                공용 Space는 WD 모델 Provider 미배포·큐 제한으로 배치 검사에 쓰지 않습니다.
              </p>
            </div>

            <div className="field full-width">
              <label>알림 타이밍</label>
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
            </div>

            <div className="field full-width">
              <label>알림 표시 방식</label>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="notification_display"
                    value="toast"
                    checked={notificationDisplay === "toast"}
                    onChange={() => setNotificationDisplay("toast")}
                  />
                  앱 내 토스트 알림 (항상 동작)
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="notification_display"
                    value="browser"
                    checked={notificationDisplay === "browser"}
                    onChange={() => setNotificationDisplay("browser")}
                  />
                  브라우저 알림 (OS 알림 센터)
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="notification_display"
                    value="both"
                    checked={notificationDisplay === "both"}
                    onChange={() => setNotificationDisplay("both")}
                  />
                  둘 다
                </label>
              </div>
              <p className="field-help">
                브라우저 알림은 OS 권한이 필요하며, 완전한 브라우저 환경이 아닌 경우 동작하지 않을 수 있습니다.
              </p>
              {(notificationDisplay === "browser" || notificationDisplay === "both") && (
                <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 12 }}>
                  {notifPermission === "granted" && (
                    <span style={{ color: "var(--success)", fontSize: 13 }}>
                      브라우저 알림 권한이 허용되어 있습니다.
                    </span>
                  )}
                  {notifPermission === "denied" && (
                    <span style={{ color: "var(--danger)", fontSize: 13 }}>
                      브라우저 알림이 차단되어 있습니다. 브라우저 설정에서 알림을 허용해주세요.
                    </span>
                  )}
                  {notifPermission === "default" && (
                    <>
                      <span style={{ fontSize: 13 }}>브라우저 알림 권한이 아직 설정되지 않았습니다.</span>
                      <button
                        type="button"
                        className="btn btn-small"
                        onClick={() => {
                          void ensureNotificationPermission().then((granted) => {
                            setNotifPermission(getNotificationPermissionStatus());
                            if (granted) setSavedMessage("브라우저 알림 권한이 허용되었습니다.");
                          });
                        }}
                      >
                        권한 요청
                      </button>
                    </>
                  )}
                  {notifPermission === "unsupported" && (
                    <span style={{ color: "var(--text-muted)", fontSize: 13 }}>
                      이 환경은 브라우저 알림을 지원하지 않습니다. 앱 내 토스트를 사용하세요.
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="modal-actions">
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </form>
      ) : null}

      {!loading ? (
        <div className="panel" style={{ marginTop: 20 }}>
          <h2 className="section-title">WD 태거 모델 (로컬)</h2>
          <p className="field-help">
            이미지 생성 직후 캐릭터 재현(identity) 검사와 Pending 재검사는 모두 이 컴퓨터에 내려받은
            로컬 WD ONNX 모델로만 동작합니다. HF Inference API·공용 Gradio Space는 사용하지 않습니다.
            모델을 설치하기 전에는 identity 결과가 <code>tagger_model_unavailable</code> 경고로
            기록됩니다.
          </p>

          {wdModelActionError ? <div className="error-banner">{wdModelActionError}</div> : null}

          {wdModelLoading ? (
            <div className="empty-state">모델 상태를 불러오는 중...</div>
          ) : wdModelStatus ? (
            <div className="job-running-card" style={{ marginBottom: 12 }}>
              <div className="job-running-meta-row">
                <span
                  className={`job-phase-badge job-phase-default`}
                  style={
                    wdModelInstalled
                      ? { color: "var(--success)" }
                      : wdModelStatus.downloading
                        ? undefined
                        : { color: "var(--danger)" }
                  }
                >
                  {wdModelInstalled ? "설치됨" : wdModelStatus.downloading ? "다운로드 중" : "설치되지 않음"}
                </span>
                <div className="job-running-meta-spacer" />
                <span className="job-running-count">{wdModelStatus.repo_id}</span>
                {wdModelPercent !== null ? (
                  <span className="job-running-pct-badge">{wdModelPercent}%</span>
                ) : null}
              </div>
              {wdModelStatus.downloading ? (
                <>
                  <div
                    className={`progress-bar job-running-bar${wdModelPercent === null ? " progress-bar-indeterminate" : ""}`}
                  >
                    <div
                      className="progress-bar-fill"
                      style={wdModelPercent !== null ? { width: `${wdModelPercent}%` } : undefined}
                    />
                  </div>
                  <div className="job-running-message">
                    {formatBytes(wdModelStatus.bytes_downloaded)}
                    {wdModelStatus.total_bytes ? ` / ${formatBytes(wdModelStatus.total_bytes)}` : " (전체 크기 확인 중...)"}
                    {wdModelStatus.current_file ? ` · ${wdModelStatus.current_file}` : ""}
                  </div>
                </>
              ) : null}
              {!wdModelStatus.downloading && !wdModelInstalled ? (
                <div className="job-running-message">
                  모델이 아직 설치되지 않았습니다. 아래 버튼으로 다운로드를 시작하세요 (모델 파일
                  크기가 크므로 시간이 걸릴 수 있습니다).
                </div>
              ) : null}
              {wdModelStatus.error ? (
                <div className="job-running-message" style={{ color: "var(--danger)" }} title={wdModelStatus.error}>
                  {wdModelStatus.error}
                </div>
              ) : null}
              <p className="field-help" style={{ marginTop: 8, marginBottom: 0 }}>
                저장 경로: <code>{wdModelStatus.cache_dir}</code>
              </p>
            </div>
          ) : null}

          <div className="modal-actions" style={{ justifyContent: "flex-start" }}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={wdModelLoading || wdModelStarting || wdModelInstalled || (wdModelStatus?.downloading ?? false)}
              onClick={() => void handleStartWdModelDownload()}
            >
              {wdModelStarting
                ? "시작하는 중..."
                : wdModelStatus?.downloading
                  ? "다운로드 중..."
                  : wdModelInstalled
                    ? "설치 완료"
                    : "모델 다운로드"}
            </button>
            {wdModelStatus?.downloading ? (
              <button
                type="button"
                className="btn btn-small"
                disabled={wdModelCancelling}
                onClick={() => void handleCancelWdModelDownload()}
              >
                {wdModelCancelling ? "취소하는 중..." : "취소"}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {!loading ? (
        <div className="panel" style={{ marginTop: 20 }}>
          <h2 className="section-title">Pending 이미지 재검사</h2>
          <p className="field-help">
            기본 대상은 리뷰 미완료·비거절 이미지 중 identity_reasons에{" "}
            <code>tagger_error</code> 등 태거 실패 코드가 있는 항목입니다. 태그·외형 정보는 변경하지
            않고 정체성(identity) 판정만 다시 계산하며, 위 <strong>WD 태거 모델</strong> 섹션의
            로컬 ONNX로만 동작합니다.
          </p>

          {!wdModelLoading && !wdModelInstalled ? (
            <div className="error-banner">
              로컬 WD 모델이 설치되어 있지 않아 재검사를 시작할 수 없습니다. 위 'WD 태거 모델'
              섹션에서 모델을 먼저 다운로드하세요.
            </div>
          ) : null}

          {recheckActionError ? <div className="error-banner">{recheckActionError}</div> : null}

          <div className="field full-width">
            <label htmlFor="recheck-batch-size">배치 크기 (100~500)</label>
            <div className="settings-range-row">
              <input
                id="recheck-batch-size"
                type="range"
                min={100}
                max={500}
                step={50}
                value={recheckBatchSize}
                disabled={isRecheckActive}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  setRecheckBatchSize(value);
                  void loadRecheckPreview(value, recheckTaggerFailuresOnly);
                }}
              />
              <strong>{recheckBatchSize}</strong>
            </div>
          </div>

          <div className="field full-width">
            <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={recheckTaggerFailuresOnly}
                disabled={isRecheckActive}
                onChange={(event) => {
                  const next = event.target.checked;
                  setRecheckTaggerFailuresOnly(next);
                  void loadRecheckPreview(recheckBatchSize, next);
                }}
              />
              태거 실패 이미지만 재검사 (권장)
            </label>
            <p className="field-help">
              끄면 리뷰 미완료·비거절 pending 이미지 전체를 재검사합니다.
            </p>
          </div>

          <div className="settings-range-row" style={{ marginTop: 4, marginBottom: 4 }}>
            {recheckPreviewLoading ? (
              <span className="field-help">미리보기를 불러오는 중...</span>
            ) : recheckPreviewError ? (
              <span style={{ color: "var(--danger)", fontSize: 13 }}>{recheckPreviewError}</span>
            ) : recheckPreview ? (
              <span>
                재검사 대상(리뷰 미완료) 이미지: <strong>{recheckPreview.eligible_images.toLocaleString()}</strong>장
                {recheckPreview.excluded_completed !== undefined ? (
                  <>
                    {" · 리뷰 완료 제외 "}
                    <strong>{recheckPreview.excluded_completed.toLocaleString()}</strong>장
                  </>
                ) : null}
                {recheckPreview.missing_files !== undefined ? (
                  <>
                    {" · 파일 누락 추정 "}
                    <strong>{recheckPreview.missing_files.toLocaleString()}</strong>장
                  </>
                ) : null}
              </span>
            ) : null}
            <button
              type="button"
              className="btn btn-small"
              disabled={recheckPreviewLoading}
              onClick={() => void loadRecheckPreview(recheckBatchSize)}
            >
              미리보기 새로고침
            </button>
          </div>
          {recheckPreview &&
          recheckPreview.excluded_completed === undefined &&
          recheckPreview.missing_files === undefined ? (
            <p className="field-help" style={{ marginTop: 0, marginBottom: 12 }}>
              이 미리보기는 재검사 대상(리뷰 미완료) 이미지 수만 제공합니다. 리뷰 완료 제외 수·파일
              누락 수는 이 백엔드 버전에서 제공되지 않습니다.
            </p>
          ) : (
            <div style={{ marginBottom: 12 }} />
          )}

          {recheckJob ? (
            <div className="job-running-card" style={{ marginBottom: 12 }}>
              <div className="job-running-meta-row">
                <span className="job-phase-badge job-phase-default">
                  {recheckStatusLabels[recheckJob.status] ?? recheckJob.status}
                </span>
                <div className="job-running-meta-spacer" />
                <span className="job-running-count">
                  {recheckJob.total > 0
                    ? `${recheckJob.current.toLocaleString()} / ${recheckJob.total.toLocaleString()}`
                    : ""}
                  {" · 완료 "}
                  {recheckJob.completed.toLocaleString()}
                  {recheckJob.succeeded !== undefined ? (
                    <>
                      {" (성공 "}
                      {recheckJob.succeeded.toLocaleString()}
                      {recheckJob.warnings !== undefined ? (
                        <>
                          {" · 경고 "}
                          {recheckJob.warnings.toLocaleString()}
                        </>
                      ) : null}
                      {recheckJob.rejected !== undefined ? (
                        <>
                          {" · 거부 "}
                          {recheckJob.rejected.toLocaleString()}
                        </>
                      ) : null}
                      {")"}
                    </>
                  ) : null}
                  {" · 실패 "}
                  {recheckJob.failed.toLocaleString()}
                  {" · 파일 누락(건너뜀) "}
                  {recheckJob.skipped.toLocaleString()}
                </span>
                {recheckPercent !== null ? (
                  <span className="job-running-pct-badge">{recheckPercent}%</span>
                ) : null}
              </div>
              <div
                className={`progress-bar job-running-bar${recheckPercent === null ? " progress-bar-indeterminate" : ""}`}
              >
                <div
                  className="progress-bar-fill"
                  style={recheckPercent !== null ? { width: `${recheckPercent}%` } : undefined}
                />
              </div>
              {recheckJob.current_character_tag ? (
                <div className="job-running-message">
                  현재: {recheckJob.current_character_tag}
                  {recheckJob.identity_status
                    ? ` — 판정: ${identityStatusLabels[recheckJob.identity_status] ?? recheckJob.identity_status}`
                    : ""}
                </div>
              ) : null}
              {!isRecheckActive ? (
                <div className="job-running-message">
                  {recheckJob.status === "completed"
                    ? `재검사가 끝났습니다 — 성공 ${recheckJob.succeeded ?? recheckJob.completed}건` +
                      (recheckJob.warnings !== undefined ? `, 경고 ${recheckJob.warnings}건` : "") +
                      (recheckJob.rejected !== undefined ? `, 거부 ${recheckJob.rejected}건` : "") +
                      `, 실패 ${recheckJob.failed}건, 파일 누락(건너뜀) ${recheckJob.skipped}건.`
                    : recheckJob.status === "cancelled"
                      ? "재검사가 취소되었습니다."
                      : recheckJob.status === "failed"
                        ? "재검사가 실패했습니다."
                        : ""}
                </div>
              ) : null}
              {recheckIdentityReasonBreakdown.length > 0 || recheckErrorBreakdown.length > 0 ? (
                <div className="recheck-diagnosis">
                  {recheckPrimaryIssue ? (
                    <div className="recheck-diagnosis-primary">
                      <strong>
                        주요 원인: {recheckPrimaryIssue.label} ({recheckPrimaryIssue.code})
                      </strong>
                      {recheckPrimaryIssue.detail ? (
                        <div className="recheck-diagnosis-detail">{recheckPrimaryIssue.detail}</div>
                      ) : null}
                    </div>
                  ) : null}
                  {recheckIdentityReasonBreakdown.length > 0 ? (
                    <div className="recheck-diagnosis-section">
                      <div className="recheck-diagnosis-heading">판정 사유별 건수</div>
                      <ul className="recheck-diagnosis-list">
                        {recheckIdentityReasonBreakdown.map((entry) => (
                          <li key={`identity-${entry.code}`}>
                            {entry.label}
                            <span className="recheck-diagnosis-count">{entry.count}건</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {recheckErrorBreakdown.length > 0 ? (
                    <div className="recheck-diagnosis-section">
                      <div className="recheck-diagnosis-heading">오류 유형별 건수</div>
                      <ul className="recheck-diagnosis-list">
                        {recheckErrorBreakdown.map((entry) => (
                          <li key={`error-${entry.code}`}>
                            {entry.label}
                            <span className="recheck-diagnosis-count">{entry.count}건</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {recheckHasConfigIssue ? (
                    <div className="recheck-diagnosis-guidance">
                      재검사를 다시 시작하기 전에 다음을 순서대로 확인하세요:
                      <ol>
                        <li>설정에 등록된 HF 토큰이 유효한지 확인</li>
                        <li>해당 계정이 사용 중인 모델에 접근할 권한이 있는지 확인</li>
                        <li>모델이 사용 가능한 상태로 배포되어 있는지 확인</li>
                        <li>전용(dedicated) 엔드포인트가 필요한 모델이라면 관련 설정이 올바른지 확인</li>
                        <li>위 사항을 모두 점검한 뒤 재검사를 다시 시작</li>
                      </ol>
                    </div>
                  ) : null}
                </div>
              ) : null}
              {recheckJob.message ? (
                <div className="job-running-message" title={recheckJob.message}>
                  {recheckJob.message}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="modal-actions" style={{ justifyContent: "flex-start" }}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={
                isRecheckActive ||
                recheckStarting ||
                recheckPreviewLoading ||
                !recheckPreview ||
                recheckPreview.eligible_images === 0 ||
                !wdModelInstalled
              }
              onClick={() => void handleStartRecheck()}
            >
              {recheckStarting ? "시작하는 중..." : "재검사 시작"}
            </button>
            {isRecheckActive ? (
              <button type="button" className="btn btn-small" onClick={() => void handleCancelRecheck()}>
                취소
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
