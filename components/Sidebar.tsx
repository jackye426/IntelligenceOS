"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/accounts",  label: "Accounts",  icon: "A" },
  { href: "/pipeline",  label: "Pipeline",  icon: "P" },
  { href: "/research",  label: "Research",  icon: "R" },
  { href: "/outreach",  label: "Outreach",  icon: "O" },
  { href: "/ask",       label: "Ask",       icon: "?" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar" aria-label="Primary navigation">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">D</span>
        <div>
          <strong>DocMap</strong>
          <span>Clinic Intelligence</span>
        </div>
      </div>

      <nav className="nav" aria-label="Sections">
        {navItems.map(({ href, label, icon }) => {
          // Mark active if the current path starts with this href.
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`nav-item${active ? " active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              <span className="nav-item-icon" aria-hidden="true">{icon}</span>
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <span className="status-dot" aria-hidden="true" />
        <span>Internal only</span>
      </div>
    </aside>
  );
}
