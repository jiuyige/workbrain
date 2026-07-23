import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { OrganizationSelector } from "../organization/OrganizationSelector";

const navigationItems = [
  { to: "/", label: "工作台", end: true },
  { to: "/organizations", label: "组织与成员" },
  { to: "/knowledge-bases", label: "企业知识库" },
  { to: "/documents", label: "文档管理" },
  { to: "/chat", label: "AI 问答" },
  { to: "/service-catalog", label: "IT 服务目录" },
  { to: "/service-agent", label: "服务助手" },
  { to: "/service-requests", label: "我的申请" },
  { to: "/approvals", label: "申请审批" },
];

export function AppLayout() {
  const { currentUser, logout } = useAuth();
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-heading">
          <div className="brand">
            <span className="brand-mark">WB</span>
            <div>
              <strong>WorkBrain</strong>
              <span>企业智能工作台</span>
            </div>
          </div>
          <button
            type="button"
            className="navigation-toggle"
            aria-label={isNavigationOpen ? "关闭导航" : "打开导航"}
            aria-controls="main-navigation"
            aria-expanded={isNavigationOpen}
            onClick={() => setIsNavigationOpen((current) => !current)}
          >
            <span aria-hidden="true" />
            菜单
          </button>
        </div>
        <nav
          id="main-navigation"
          aria-label="主导航"
          className={
            isNavigationOpen ? "main-navigation open" : "main-navigation"
          }
        >
          {navigationItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                isActive ? "navigation-link active" : "navigation-link"
              }
              onClick={() => setIsNavigationOpen(false)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="content-column">
        <header className="topbar">
          <OrganizationSelector />
          <div className="user-menu">
            <span className="user-placeholder">{currentUser?.username}</span>
            <button type="button" className="logout-button" onClick={logout}>
              退出登录
            </button>
          </div>
        </header>
        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
