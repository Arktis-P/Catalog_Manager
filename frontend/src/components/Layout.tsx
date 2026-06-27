import { NavLink, Outlet } from "react-router-dom";
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

export function Layout() {
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
        <GlobalTaskBar />
      </div>
      <main className="page-container">
        <BackendGate>
          <Outlet />
        </BackendGate>
      </main>
      <ToastContainer />
    </div>
  );
}
