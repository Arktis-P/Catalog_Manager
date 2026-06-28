import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { WikiPanelProvider, useWikiPanel } from "../context/WikiPanelContext";
import { BackendGate } from "./BackendGate";
import { GlobalTaskBar } from "./GlobalTaskBar";
import { ToastContainer } from "./ToastContainer";

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
const DEFAULT_WIKI_HEIGHT = 320;
const MIN_WIKI_HEIGHT = 120;
const MAX_WIKI_HEIGHT = 900;

function proxyUrl(url: string): string {
  return `/api/wiki-proxy?url=${encodeURIComponent(url)}`;
}

function LayoutInner() {
  const { wikiUrl, wikiCursor, wikiHistory, openWiki, closeWiki, wikiBack, wikiForward } =
    useWikiPanel();

  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH);
  const [wikiHeight, setWikiHeight] = useState(DEFAULT_WIKI_HEIGHT);
  const isDragging = useRef(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(DEFAULT_SIDEBAR_WIDTH);
  const isWikiDragging = useRef(false);
  const wikiDragStartY = useRef(0);
  const wikiDragStartHeight = useRef(DEFAULT_WIKI_HEIGHT);

  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    dragStartX.current = e.clientX;
    dragStartWidth.current = sidebarWidth;
    e.preventDefault();
  }, [sidebarWidth]);

  const onWikiResizeMouseDown = useCallback((e: React.MouseEvent) => {
    isWikiDragging.current = true;
    wikiDragStartY.current = e.clientY;
    wikiDragStartHeight.current = wikiHeight;
    e.preventDefault();
  }, [wikiHeight]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (isDragging.current) {
        const delta = dragStartX.current - e.clientX;
        const newWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, dragStartWidth.current + delta));
        setSidebarWidth(newWidth);
      }
      if (isWikiDragging.current) {
        const delta = wikiDragStartY.current - e.clientY;
        const newHeight = Math.min(MAX_WIKI_HEIGHT, Math.max(MIN_WIKI_HEIGHT, wikiDragStartHeight.current + delta));
        setWikiHeight(newHeight);
      }
    };
    const onMouseUp = () => { isDragging.current = false; isWikiDragging.current = false; };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "wiki-navigate" && typeof e.data.url === "string") {
        openWiki(e.data.url);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [openWiki]);

  return (
    <div className="app-shell">
      <div className="app-top">
        <header className="top-nav">
          <div className="top-nav-inner">
            <div className="brand">
              <span className="brand-title">Catalogue Manager</span>
              <span className="brand-subtitle">Danbooru character catalog desktop app</span>
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
        <main className="page-container">
          <BackendGate>
            <Outlet context={{ openWiki }} />
          </BackendGate>
        </main>
        <aside className="right-sidebar" style={{ width: sidebarWidth }}>
          <div className="sidebar-resize-handle" onMouseDown={onResizeMouseDown} />
          <div className="right-sidebar-tasks">
            <GlobalTaskBar />
          </div>
          {wikiUrl ? (
            <div className="right-sidebar-wiki" style={{ height: wikiHeight }}>
              <div className="wiki-panel-resize-handle" onMouseDown={onWikiResizeMouseDown} />
              <div className="wiki-panel-header">
                <button
                  className="btn btn-ghost wiki-nav-btn"
                  type="button"
                  disabled={wikiCursor <= 0}
                  title="뒤로"
                  onClick={wikiBack}
                >
                  ‹
                </button>
                <button
                  className="btn btn-ghost wiki-nav-btn"
                  type="button"
                  disabled={wikiCursor >= wikiHistory.length - 1}
                  title="앞으로"
                  onClick={wikiForward}
                >
                  ›
                </button>
                <span className="wiki-panel-url" title={wikiUrl}>
                  {wikiUrl}
                </span>
                <a
                  href={wikiUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-ghost wiki-nav-btn"
                  title="외부 브라우저에서 열기"
                >
                  ↗
                </a>
                <button
                  className="btn btn-ghost wiki-nav-btn"
                  type="button"
                  title="닫기"
                  onClick={closeWiki}
                >
                  ✕
                </button>
              </div>
              <iframe
                key={proxyUrl(wikiUrl)}
                src={proxyUrl(wikiUrl)}
                className="wiki-iframe"
                title="Wiki"
              />
            </div>
          ) : null}
        </aside>
      </div>
      <ToastContainer />
    </div>
  );
}

export function Layout() {
  return (
    <WikiPanelProvider>
      <LayoutInner />
    </WikiPanelProvider>
  );
}
