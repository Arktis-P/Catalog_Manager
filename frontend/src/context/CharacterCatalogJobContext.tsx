import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { CatalogJob } from "../types";
import { useNotificationMode } from "./NotificationModeContext";
import { ensureNotificationPermission, showTaskCompleteNotification } from "../utils/notifications";

interface CharacterCatalogJobContextValue {
  jobs: CatalogJob[];
  startListJob: (minPostCount: number, restart?: boolean) => Promise<CatalogJob>;
  startTagsJob: (characterIds: number[]) => Promise<CatalogJob>;
  retryFailed: (limit?: number) => Promise<CatalogJob>;
  cancelJob: (jobId: string) => Promise<void>;
  pauseJob: (jobId: string) => Promise<void>;
  resumeJob: (jobId: string) => Promise<void>;
  dismissJob: (jobId: string) => void;
  isJobActive: (jobType?: CatalogJob["job_type"]) => boolean;
  lastError: string | null;
  clearLastError: () => void;
}

const CharacterCatalogJobContext = createContext<CharacterCatalogJobContextValue | null>(null);

function upsertJob(jobs: CatalogJob[], nextJob: CatalogJob): CatalogJob[] {
  const index = jobs.findIndex((job) => job.job_id === nextJob.job_id);
  if (index === -1) {
    return [nextJob, ...jobs];
  }
  const copy = [...jobs];
  copy[index] = nextJob;
  return copy;
}

function notifyJobComplete(job: CatalogJob) {
  if (job.job_type === "character_catalog_list") {
    showTaskCompleteNotification("캐릭터 목록 수집 완료", `신규 ${job.created} · 갱신 ${job.updated}`);
    return;
  }
  showTaskCompleteNotification(
    "캐릭터 통합 태그 수집 완료",
    `성공 ${job.success_count} · 부분 완료 ${job.partial_count} · 실패 ${job.failed_count}`,
  );
}

export function CharacterCatalogJobProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<CatalogJob[]>([]);
  const [dismissedJobIds, setDismissedJobIds] = useState<Set<string>>(() => new Set());
  const [lastError, setLastError] = useState<string | null>(null);
  const notifiedJobIdsRef = useRef<Set<string>>(new Set());
  const { mode: notificationMode } = useNotificationMode();
  const notificationModeRef = useRef(notificationMode);
  notificationModeRef.current = notificationMode;

  const visibleJobs = useMemo(
    () => jobs.filter((job) => !dismissedJobIds.has(job.job_id)),
    [jobs, dismissedJobIds],
  );

  const runningJobIds = useMemo(
    () =>
      visibleJobs
        .filter((job) => job.status === "queued" || job.status === "running" || job.status === "paused")
        .map((job) => job.job_id),
    [visibleJobs],
  );

  useEffect(() => {
    void ensureNotificationPermission();
  }, []);

  const handleJobUpdates = useCallback((updates: CatalogJob[], previous: CatalogJob[]) => {
    for (const job of updates) {
      const prior = previous.find((item) => item.job_id === job.job_id);
      if (!prior || prior.status === job.status) {
        continue;
      }
      if (job.status === "completed" && !notifiedJobIdsRef.current.has(job.job_id)) {
        notifiedJobIdsRef.current.add(job.job_id);
        if (notificationModeRef.current === "each") {
          notifyJobComplete(job);
        }
      }
      if (job.status === "failed" && !notifiedJobIdsRef.current.has(job.job_id)) {
        notifiedJobIdsRef.current.add(job.job_id);
        if (notificationModeRef.current === "each") {
          showTaskCompleteNotification("캐릭터 카탈로그 작업 실패", job.error || job.message);
        }
      }
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const response = await api.listCatalogJobs();
      setJobs((current) => {
        let merged = current;
        for (const job of response.items) {
          merged = upsertJob(merged, job);
        }
        handleJobUpdates(response.items, current);
        return merged;
      });
    } catch {
      // Ignore refresh errors during polling.
    }
  }, [handleJobUpdates]);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    if (runningJobIds.length === 0) {
      return;
    }
    const poll = async () => {
      try {
        const updates = await Promise.all(runningJobIds.map((jobId) => api.getCatalogJob(jobId)));
        setJobs((current) => {
          handleJobUpdates(updates, current);
          let merged = current;
          for (const job of updates) {
            merged = upsertJob(merged, job);
          }
          return merged;
        });
      } catch {
        // Ignore transient poll errors.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1000);
    return () => window.clearInterval(timer);
  }, [runningJobIds.join("|"), handleJobUpdates]);

  const registerStartedJob = useCallback((job: CatalogJob) => {
    setDismissedJobIds((current) => {
      if (!current.has(job.job_id)) return current;
      const next = new Set(current);
      next.delete(job.job_id);
      return next;
    });
    setJobs((current) => upsertJob(current, job));
  }, []);

  const startListJob = useCallback(async (minPostCount: number, restart = false) => {
    setLastError(null);
    const job = await api.startCatalogListJob(minPostCount, restart);
    registerStartedJob(job);
    return job;
  }, [registerStartedJob]);

  const startTagsJob = useCallback(async (characterIds: number[]) => {
    setLastError(null);
    const job = await api.startCatalogTagsJob(characterIds);
    registerStartedJob(job);
    return job;
  }, [registerStartedJob]);

  const retryFailed = useCallback(async (limit = 500) => {
    setLastError(null);
    const job = await api.retryFailedCatalogTags(limit);
    registerStartedJob(job);
    return job;
  }, [registerStartedJob]);

  const dismissJob = useCallback((jobId: string) => {
    setDismissedJobIds((current) => new Set(current).add(jobId));
  }, []);

  const cancelJob = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = await api.cancelCatalogJob(jobId);
      setJobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to cancel job");
    }
  }, []);

  const pauseJob = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = await api.pauseCatalogJob(jobId);
      setJobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to pause job");
    }
  }, []);

  const resumeJob = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = await api.resumeCatalogJob(jobId);
      setJobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to resume job");
    }
  }, []);

  const isJobActive = useCallback(
    (jobType?: CatalogJob["job_type"]) =>
      visibleJobs.some(
        (job) =>
          (jobType ? job.job_type === jobType : true) &&
          (job.status === "queued" || job.status === "running" || job.status === "paused"),
      ),
    [visibleJobs],
  );

  const value = useMemo(
    () => ({
      jobs: visibleJobs,
      startListJob,
      startTagsJob,
      retryFailed,
      cancelJob,
      pauseJob,
      resumeJob,
      dismissJob,
      isJobActive,
      lastError,
      clearLastError: () => setLastError(null),
    }),
    [visibleJobs, startListJob, startTagsJob, retryFailed, cancelJob, pauseJob, resumeJob, dismissJob, isJobActive, lastError],
  );

  return <CharacterCatalogJobContext.Provider value={value}>{children}</CharacterCatalogJobContext.Provider>;
}

export function useCharacterCatalogJobs() {
  const context = useContext(CharacterCatalogJobContext);
  if (!context) {
    throw new Error("useCharacterCatalogJobs must be used within CharacterCatalogJobProvider");
  }
  return context;
}
