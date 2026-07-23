import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";

import App from "../App";
import { setActiveOrganizationId, setAuthSession } from "../auth/session";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderAuthenticatedApp(path: string) {
  setAuthSession("organization-jwt");
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

const organizations = [
  {
    id: 1,
    name: "Platform Team",
    slug: "platform-team",
    role: "admin",
    created_at: "2026-07-21T08:00:00Z",
  },
  {
    id: 2,
    name: "Support Team",
    slug: "support-team",
    role: "member",
    created_at: "2026-07-21T08:00:00Z",
  },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("organization-scoped pages", () => {
  it("switches organization and reloads knowledge bases with the new header", async () => {
    setActiveOrganizationId(1);
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 10, username: "admin" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations }));
      }
      if (input.endsWith("/knowledge-bases")) {
        const organizationId = new Headers(options?.headers).get(
          "X-Organization-ID",
        );
        const name = organizationId === "2" ? "Support Runbooks" : "Platform Docs";
        return Promise.resolve(
          jsonResponse({
            knowledge_bases: [
              {
                id: organizationId === "2" ? 202 : 101,
                organization_id: Number(organizationId),
                created_by_user_id: 10,
                name,
                description: "Team documentation",
                created_at: "2026-07-21T08:00:00Z",
                updated_at: "2026-07-21T08:00:00Z",
              },
            ],
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAuthenticatedApp("/knowledge-bases");

    expect(await screen.findByText("Platform Docs")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("当前组织"), {
      target: { value: "2" },
    });

    expect(await screen.findByText("Support Runbooks")).toBeInTheDocument();
    expect(localStorage.getItem("workbrain.organization_id")).toBe("2");
    await waitFor(() => {
      const knowledgeCalls = fetchMock.mock.calls.filter(
        ([url]) => typeof url === "string" && url.endsWith("/knowledge-bases"),
      );
      const lastHeaders = new Headers(knowledgeCalls.at(-1)?.[1]?.headers);
      expect(lastHeaders.get("X-Organization-ID")).toBe("2");
    });
  });

  it("lets an admin list, invite and disable organization members", async () => {
    setActiveOrganizationId(1);
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      const method = options?.method || "GET";
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 10, username: "admin" }));
      }
      if (input.endsWith("/organizations") && method === "GET") {
        return Promise.resolve(jsonResponse({ organizations: [organizations[0]] }));
      }
      if (input.endsWith("/organizations/members") && method === "GET") {
        return Promise.resolve(
          jsonResponse({
            members: [
              {
                id: 11,
                user_id: 10,
                username: "admin",
                role: "admin",
                is_active: true,
                created_at: "2026-07-21T08:00:00Z",
              },
              {
                id: 12,
                user_id: 12,
                username: "old-member",
                role: "member",
                is_active: true,
                created_at: "2026-07-21T08:00:00Z",
              },
            ],
          }),
        );
      }
      if (input.endsWith("/organizations/members") && method === "POST") {
        return Promise.resolve(
          jsonResponse(
            {
              id: 13,
              user_id: 13,
              username: "new-approver",
              role: "approver",
              is_active: true,
              created_at: "2026-07-21T08:00:00Z",
            },
            201,
          ),
        );
      }
      if (input.endsWith("/organizations/members/12/disable")) {
        return Promise.resolve(
          jsonResponse({
            id: 12,
            user_id: 12,
            username: "old-member",
            role: "member",
            is_active: false,
            created_at: "2026-07-21T08:00:00Z",
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAuthenticatedApp("/organizations");

    expect(await screen.findByText("old-member")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("成员用户名"), {
      target: { value: "new-approver" },
    });
    fireEvent.change(screen.getByLabelText("成员角色"), {
      target: { value: "approver" },
    });
    fireEvent.click(screen.getByRole("button", { name: "添加成员" }));
    expect(await screen.findByText("new-approver")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "停用成员 old-member" }),
    );
    expect(await screen.findByText("已停用")).toBeInTheDocument();
  });

  it("keeps member management and knowledge editing hidden from members", async () => {
    setActiveOrganizationId(2);
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "reader" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organizations[1]] }));
      }
      if (input.endsWith("/knowledge-bases")) {
        return Promise.resolve(jsonResponse({ knowledge_bases: [] }));
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = renderAuthenticatedApp("/organizations");

    expect(
      await screen.findByText("只有组织管理员可以管理成员。"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("成员用户名")).not.toBeInTheDocument();
    unmount();

    renderAuthenticatedApp("/knowledge-bases");
    expect(await screen.findByText("当前知识库为空")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "创建知识库" }),
    ).not.toBeInTheDocument();
  });

  it("lets an admin create a knowledge base in the active organization", async () => {
    setActiveOrganizationId(1);
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      const method = options?.method || "GET";
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 10, username: "admin" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organizations[0]] }));
      }
      if (input.endsWith("/knowledge-bases") && method === "GET") {
        return Promise.resolve(jsonResponse({ knowledge_bases: [] }));
      }
      if (input.endsWith("/knowledge-bases") && method === "POST") {
        return Promise.resolve(
          jsonResponse(
            {
              id: 301,
              organization_id: 1,
              created_by_user_id: 10,
              name: "Security Handbook",
              description: "Security policies",
              created_at: "2026-07-21T08:00:00Z",
              updated_at: "2026-07-21T08:00:00Z",
            },
            201,
          ),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAuthenticatedApp("/knowledge-bases");

    const nameInput = await screen.findByLabelText("知识库名称");
    expect(
      screen.getByText("在文档管理中上传、处理并发布知识库文档。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("文档将在下一阶段添加到知识库。"),
    ).not.toBeInTheDocument();
    await screen.findByText("当前知识库为空");
    fireEvent.change(nameInput, {
      target: { value: "Security Handbook" },
    });
    fireEvent.change(screen.getByLabelText("知识库说明"), {
      target: { value: "Security policies" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建知识库" }));

    let postCall: (typeof fetchMock.mock.calls)[number] | undefined;
    await waitFor(() => {
      postCall = fetchMock.mock.calls.find(
        ([url, options]) =>
          typeof url === "string" &&
          url.endsWith("/knowledge-bases") &&
          options?.method === "POST",
      );
      expect(postCall).toBeDefined();
    });
    expect(await screen.findByText("Security Handbook")).toBeInTheDocument();
    expect(new Headers(postCall?.[1]?.headers).get("X-Organization-ID")).toBe(
      "1",
    );
  });
});
