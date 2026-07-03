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

const navItems = [
  { to: "/", label: "Catalog", end: true },
  { to: "/review", label: "Review" },
  { to: "/series", label: "Series" },
  { to: "/generation", label: "Generation" },
  { to: "/settings", label: "Settings" },
];

const DEFAULT_SIDEBAR_WIDTH = 450;
const MIN_SIDEBAR_WIDTH = 200;
const MAX_SIDEBAR_WIDTH = 900;

export function Layout() {
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH);
  const isDragging = useRef(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(DEFAULT_SIDEBAR_WIDTH);

  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    dragStartX.current = e.clientX;
    dragStartWidth.current = sidebarWidth;
    e.preventDefault();
  }, [sidebarWidth]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (isDragging.current) {
        const delta = e.clientX - dragStartX.current;
        const newWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, dragStartWidth.current + delta));
        setSidebarWidth(newWidth);
      }
    };
    const onMouseUp = () => { isDragging.current = false; };
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
            <nav className="nav-links">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </header>
      </div>
      <div className="app-body">
        <aside className="right-sidebar" style={{ width: sidebarWidth }}>
          <div className="right-sidebar-tasks">
            <GlobalTaskBar />
          </div>
          <div className="sidebar-resize-handle" onMouseDown={onResizeMouseDown} />
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
