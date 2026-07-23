import { Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { AppLayout } from "./layout/AppLayout";
import { OrganizationProvider } from "./organization/OrganizationContext";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { ChatPage } from "./pages/ChatPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { KnowledgeBasesPage } from "./pages/KnowledgeBasesPage";
import { LoginPage } from "./pages/LoginPage";
import { OrganizationPage } from "./pages/OrganizationPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ServiceCatalogPage } from "./pages/ServiceCatalogPage";
import { ServiceAgentPage } from "./pages/ServiceAgentPage";
import { ServiceRequestsPage } from "./pages/ServiceRequestsPage";
import { ProtectedRoute } from "./routes/ProtectedRoute";

const protectedPages = [
  {
    path: "/",
    title: "工作台",
    description: "集中查看知识库、IT 服务申请和待处理事项。",
  },
];

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route path="/organizations" element={<OrganizationPage />} />
          <Route path="/knowledge-bases" element={<KnowledgeBasesPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/service-catalog" element={<ServiceCatalogPage />} />
          <Route path="/service-agent" element={<ServiceAgentPage />} />
          <Route path="/service-requests" element={<ServiceRequestsPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          {protectedPages.map((page) => (
            <Route
              key={page.path}
              path={page.path}
              element={
                <PlaceholderPage
                  title={page.title}
                  description={page.description}
                />
              }
            />
          ))}
        </Route>
      </Route>
      <Route
        path="*"
        element={
          <PlaceholderPage
            title="页面不存在"
            description="请从主导航选择一个有效页面。"
          />
        }
      />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <OrganizationProvider>
        <AppRoutes />
      </OrganizationProvider>
    </AuthProvider>
  );
}
