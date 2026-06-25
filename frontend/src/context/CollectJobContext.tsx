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
import type { CollectJob } from "../types";
import { useNotificationMode } from "./NotificationModeContext";
import { ensureNotificationPermission, showTaskCompleteNotification } from "../utils/notifications";

interface CollectJobContextValue {
  jobs: CollectJob[];
  startCollect: (seriesId: number) => Promise<CollectJob>;
  startCollectMany: (seriesIds: number[]) => Promise<CollectJob[]>;
  startAppearanceExtract: (seriesId: number) => Promise<CollectJob>;
  cancelJob: (jobId: string) => Promise<void>;
  pauseJob: (jobId: string) => Promise<void>;
  resumeJob: (jobId: string) => Promise<void>;
  dismissJob: (jobId: string) => void;
  isProcessingSeries: (seriesId: number) => boolean;
  isCollectingSeries: (seriesId: number) => boolean;
  isExtractingAppearanceSeries: (seriesId: number) => boolean;
  lastError: string | null;
  clearLastError: () => void;
  lastCompletedJob: CollectJob | null;
  clearLastCompletedJob: () => void;
}

const CollectJobContext = createContext<CollectJobContextValue | null>(null);

function upsertJob(jobs: CollectJob[], nextJob: CollectJob): CollectJob[] {
  const index = jobs.findIndex((job) => job.job_id === nextJob.job_id);
  if (index === -1) {
    return [nextJob, ...jobs];
  }
  const copy = [...jobs];
  copy[index] = nextJob;
  return copy;
}

function notifyJobComplete(job: CollectJob) {
  if (job.job_type === "appearance_extract") {
    const title = `${job.series_tag} 외형 태그 추출 완료`;
    const body = `${job.updated}/${job.total}명 갱신`;
    showTaskCompleteNotification(title, body);
    return;
  }

  const title = `${job.series_tag} 캐릭터 수집 완료`;
  const body =
    job.created > 0
      ? `추가 ${job.created} · skip ${job.skipped_existing} · 총 discovered ${job.discovered}`
      : `신규 추가 없음 · skip ${job.skipped_existing}`;
  showTaskCompleteNotification(title, body);
}

export function CollectJobProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<CollectJob[]>([]);
  const [dismissedJobIds, setDismissedJobIds] = useState<Set<string>>(() => new Set());
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastCompletedJob, setLastCompletedJob] = useState<CollectJob | null>(null);
  const notifiedJobIdsRef = useRef<Set<string>>(new Set());
  const { mode: notificationMode } = useNotificationMode();
  const notificationModeRef = useRef(notificationMode);
  notificationModeRef.current = notificationMode;
  const allDoneCountRef = useRef(0);
  const prevRunningCountRef = useRef(0);

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

  const handleJobUpdates = useCallback((updates: CollectJob[], previous: CollectJob[]) => {
    for (const job of updates) {
      const prior = previous.find((item) => item.job_id === job.job_id);
      if (!prior || prior.status === job.status) {
        continue;
      }
      if (job.status === "completed" && !notifiedJobIdsRef.current.has(job.job_id)) {
        notifiedJobIdsRef.current.add(job.job_id);
        const mode = notificationModeRef.current;
        if (mode === "each") {
          notifyJobComplete(job);
        } else if (mode === "all_done") {
          allDoneCountRef.current++;
        }
        setLastCompletedJob(job);
      }
      if (job.status === "failed" && !notifiedJobIdsRef.current.has(job.job_id)) {
        notifiedJobIdsRef.current.add(job.job_id);
        const mode = notificationModeRef.current;
        if (mode === "each") {
          const title =
            job.job_type === "appearance_extract"
              ? `${job.series_tag} 외형 태그 추출 실패`
              : `${job.series_tag} 캐릭터 수집 실패`;
          showTaskCompleteNotification(title, job.error || job.message);
        }
      }
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const response = await api.listCollectJobs();
      setJobs((current) => {
        let merged = current;
        for (const job of response.items) {
          merged = upsertJob(merged, job);
        }
        handleJobUpdates(response.items, current);
        return merged;
      });
    } catch {
      // Ignore refresh errors during polling; pages can still start jobs.
    }
  }, [handleJobUpdates]);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  // 주기적으로 잡 목록 갱신 — 파이프라인 실행 중 새로 시작된 running 잡 발견
  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshJobs();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [refreshJobs]);

  // "모든 작업 완료 시 알림" 모드: running → idle 전환 감지
  useEffect(() => {
    const wasRunning = prevRunningCountRef.current > 0;
    prevRunningCountRef.current = runningJobIds.length;
    if (wasRunning && runningJobIds.length === 0 && notificationMode === "all_done") {
      const count = allDoneCountRef.current;
      allDoneCountRef.current = 0;
      if (count > 0) {
        showTaskCompleteNotification("모든 수집/추출 작업 완료", `${count}개 작업 완료`);
      }
    }
  }, [runningJobIds.length, notificationMode]);

  useEffect(() => {
    if (runningJobIds.length === 0) {
      return;
    }

    const poll = async () => {
      try {
        const updates = await Promise.all(runningJobIds.map((jobId) => api.getCollectJob(jobId)));
        setJobs((current) => {
          handleJobUpdates(updates, current);
          let merged = current;
          for (const job of updates) {
            merged = upsertJob(merged, job);
          }
          return merged;
        });
      } catch (err) {
        setLastError(err instanceof Error ? err.message : "Failed to poll background jobs");
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 800);
    return () => window.clearInterval(timer);
  }, [runningJobIds.join("|"), handleJobUpdates]);

  const registerStartedJob = useCallback((job: CollectJob) => {
    setDismissedJobIds((current) => {
      if (!current.has(job.job_id)) {
        return current;
      }
      const next = new Set(current);
      next.delete(job.job_id);
      return next;
    });
    setJobs((current) => upsertJob(current, job));
  }, []);

  const startCollect = useCallback(async (seriesId: number) => {
    setLastError(null);
    const job = await api.startCollectCharactersJob(seriesId);
    registerStartedJob(job);
    return job;
  }, [registerStartedJob]);

  const startCollectMany = useCallback(async (seriesIds: number[]) => {
    if (seriesIds.length === 0) {
      return [];
    }
    setLastError(null);
    if (seriesIds.length === 1) {
      const job = await api.startCollectCharactersJob(seriesIds[0]);
      registerStartedJob(job);
      return [job];
    }
    const response = await api.startCollectCharactersJobs(seriesIds);
    for (const job of response.items) {
      registerStartedJob(job);
    }
    return response.items;
  }, [registerStartedJob]);

  const startAppearanceExtract = useCallback(async (seriesId: number) => {
    setLastError(null);
    const job = await api.startAppearanceExtractJob(seriesId);
    registerStartedJob(job);
    return job;
  }, [registerStartedJob]);

  const dismissJob = useCallback((jobId: string) => {
    setDismissedJobIds((current) => new Set(current).add(jobId));
  }, []);

  const cancelJob = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = await api.cancelCollectJob(jobId);
      setJobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to cancel background job");
    }
  }, []);

  const pauseJob = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = await api.pauseCollectJob(jobId);
      setJobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to pause job");
    }
  }, []);

  const resumeJob = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = await api.resumeCollectJob(jobId);
      setJobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to resume job");
    }
  }, []);

  const isActiveJobForSeries = useCallback(
    (seriesId: number, jobType?: CollectJob["job_type"]) =>
      visibleJobs.some(
        (job) =>
          job.series_id === seriesId &&
          (jobType ? job.job_type === jobType : true) &&
          (job.status === "queued" || job.status === "running" || job.status === "paused"),
      ),
    [visibleJobs],
  );

  const isProcessingSeries = useCallback(
    (seriesId: number) => isActiveJobForSeries(seriesId),
    [isActiveJobForSeries],
  );

  const isCollectingSeries = useCallback(
    (seriesId: number) => isActiveJobForSeries(seriesId, "character_collect"),
    [isActiveJobForSeries],
  );

  const isExtractingAppearanceSeries = useCallback(
    (seriesId: number) => isActiveJobForSeries(seriesId, "appearance_extract"),
    [isActiveJobForSeries],
  );

  const value = useMemo(
    () => ({
      jobs: visibleJobs,
      startCollect,
      startCollectMany,
      startAppearanceExtract,
      cancelJob,
      pauseJob,
      resumeJob,
      dismissJob,
      isProcessingSeries,
      isCollectingSeries,
      isExtractingAppearanceSeries,
      lastError,
      clearLastError: () => setLastError(null),
      lastCompletedJob,
      clearLastCompletedJob: () => setLastCompletedJob(null),
    }),
    [
      visibleJobs,
      startCollect,
      startCollectMany,
      startAppearanceExtract,
      cancelJob,
      pauseJob,
      resumeJob,
      dismissJob,
      isProcessingSeries,
      isCollectingSeries,
      isExtractingAppearanceSeries,
      lastError,
      lastCompletedJob,
    ],
  );

  return <CollectJobContext.Provider value={value}>{children}</CollectJobContext.Provider>;
}

export function useCollectJobs() {
  const context = useContext(CollectJobContext);
  if (!context) {
    throw new Error("useCollectJobs must be used within CollectJobProvider");
  }
  return context;
}
