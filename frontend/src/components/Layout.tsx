import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { BackendGate } from "./BackendGate";
import { GlobalTaskBar } from "./GlobalTaskBar";
import { ToastContainer } from "./ToastContainer";

function BackendStatusDot() {
  const [alive, setAlive] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const res = await fetch("/api/health", { signal: AbortSignal.timeout(2000) });
        if (mounted) setAlive(res.ok);
      } catch {
        if (mounted) setAlive(false);
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), 10_000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  if (alive === null) return null;
  return (
    <span
      className={`backend-status-dot ${alive ? "backend-status-dot-ok" : "backend-status-dot-err"}`}
      title={alive ? "백엔드 연결됨" : "백엔드 연결 끊김"}
      aria-label={alive ? "백엔드 연결됨" : "백엔드 연결 끊김"}
    />
  );
}

const navGroups = [
  {
    label: "작업",
    items: [
      { to: "/series", label: "수집" },
      { to: "/generation", label: "생성" },
      { to: "/review", label: "리뷰" },
    ],
  },
  {
    label: "결과",
    items: [
      { to: "/", label: "캐릭터 카탈로그", end: true },
      { to: "/series-catalog", label: "시리즈 카탈로그" },
    ],
  },
  {
    label: "관리",
    items: [
      { to: "/characters", label: "데이터 관리" },
      { to: "/settings", label: "설정" },
    ],
  },
];

const DEFAULT_SIDEBAR_WIDTH = 450;
const MIN_SIDEBAR_WIDTH = 280;
const MAX_SIDEBAR_WIDTH = 720;
const COLLAPSED_SIDEBAR_WIDTH = 52;
const SIDEBAR_WIDTH_KEY = "catalogue-manager:task-sidebar-width";
const SIDEBAR_COLLAPSED_KEY = "catalogue-manager:task-sidebar-collapsed";

function readStoredSidebarWidth(): number {
  try {
    const stored = Number(window.localStorage.getItem(SIDEBAR_WIDTH_KEY));
    return Number.isFinite(stored)
      ? Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, stored))
      : DEFAULT_SIDEBAR_WIDTH;
  } catch {
    return DEFAULT_SIDEBAR_WIDTH;
  }
}

function readStoredSidebarCollapsed(): boolean {
  try {
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    return stored === null ? true : stored === "true";
  } catch {
    return true;
  }
}

export function Layout() {
  const [sidebarWidth, setSidebarWidth] = useState(readStoredSidebarWidth);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readStoredSidebarCollapsed);
  const isDragging = useRef(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(DEFAULT_SIDEBAR_WIDTH);

  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    if (sidebarCollapsed) return;
    isDragging.current = true;
    dragStartX.current = e.clientX;
    dragStartWidth.current = sidebarWidth;
    e.preventDefault();
  }, [sidebarCollapsed, sidebarWidth]);

  const resetSidebarWidth = useCallback(() => {
    setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
    try {
      window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(DEFAULT_SIDEBAR_WIDTH));
    } catch {
      // 저장소 접근이 막혀도 현재 세션의 레이아웃은 계속 동작한다.
    }
  }, []);

  const onResizeKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      let nextWidth: number | null = null;
      if (event.key === "ArrowLeft") nextWidth = Math.max(MIN_SIDEBAR_WIDTH, sidebarWidth - 16);
      if (event.key === "ArrowRight") nextWidth = Math.min(MAX_SIDEBAR_WIDTH, sidebarWidth + 16);
      if (event.key === "Home") nextWidth = MIN_SIDEBAR_WIDTH;
      if (event.key === "End") nextWidth = MAX_SIDEBAR_WIDTH;
      if (event.key === "Enter") nextWidth = DEFAULT_SIDEBAR_WIDTH;
      if (nextWidth === null) return;
      event.preventDefault();
      setSidebarWidth(nextWidth);
      try {
        window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(nextWidth));
      } catch {
        // 저장소 접근이 막혀도 키보드로 조절한 폭은 현재 세션에서 유지한다.
      }
    },
    [sidebarWidth],
  );

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      } catch {
        // 저장소 접근이 막혀도 현재 세션의 토글은 유지한다.
      }
      return next;
    });
  }, []);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (isDragging.current) {
        const delta = e.clientX - dragStartX.current;
        const newWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, dragStartWidth.current + delta));
        setSidebarWidth(newWidth);
      }
    };
    const onMouseUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      setSidebarWidth((current) => {
        try {
          window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(current));
        } catch {
          // 저장소 접근이 막혀도 조절된 폭은 현재 세션에서 유지한다.
        }
        return current;
      });
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  return (
    <div className="app-shell">
      <div className="app-top">
        <header className="top-nav">
          <div className="top-nav-inner">
            <div className="brand">
              <span className="brand-title">Catalogue Manager</span>
              <span className="brand-subtitle">Danbooru character catalog desktop app</span>
              <BackendStatusDot />
            </div>
            <nav className="nav-links" aria-label="주요 메뉴">
              {navGroups.map((group) => (
                <div className="nav-group" key={group.label}>
                  <span className="nav-group-label">{group.label}</span>
                  <div className="nav-group-items">
                    {group.items.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        end={item.end}
                        className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
                      >
                        {item.label}
                      </NavLink>
                    ))}
                  </div>
                </div>
              ))}
            </nav>
          </div>
        </header>
      </div>
      <div className="app-body">
        <aside
          className={`right-sidebar${sidebarCollapsed ? " right-sidebar--collapsed" : ""}`}
          style={{ width: sidebarCollapsed ? COLLAPSED_SIDEBAR_WIDTH : sidebarWidth }}
          aria-label="전역 작업 패널"
        >
          <div className="right-sidebar-tasks">
            <GlobalTaskBar collapsed={sidebarCollapsed} onToggleCollapsed={toggleSidebar} />
          </div>
          {!sidebarCollapsed ? (
            <div
              className="sidebar-resize-handle"
              role="separator"
              tabIndex={0}
              aria-orientation="vertical"
              aria-label="작업 패널 폭 조절"
              aria-valuemin={MIN_SIDEBAR_WIDTH}
              aria-valuemax={MAX_SIDEBAR_WIDTH}
              aria-valuenow={sidebarWidth}
              aria-valuetext={`${sidebarWidth}px`}
              title="드래그 또는 좌우 방향키로 폭 조절 · 더블클릭 또는 Enter로 기본 폭 복원"
              onMouseDown={onResizeMouseDown}
              onDoubleClick={resetSidebarWidth}
              onKeyDown={onResizeKeyDown}
            />
          ) : null}
        </aside>
        <main className="page-container">
          <BackendGate>
            <Outlet />
          </BackendGate>
        </main>
      </div>
      <ToastContainer />
    </div>
  );
}
