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

function renderCatalogPage() {
  setAuthSession("service-catalog-jwt");
  setActiveOrganizationId(1);
  return render(
    <MemoryRouter initialEntries={["/service-catalog"]}>
      <App />
    </MemoryRouter>,
  );
}

const organizations = [
  {
    id: 1,
    name: "Platform Team",
    slug: "platform-team",
    role: "member",
    created_at: "2026-07-21T08:00:00Z",
  },
  {
    id: 2,
    name: "Finance Team",
    slug: "finance-team",
    role: "member",
    created_at: "2026-07-21T08:00:00Z",
  },
];

const vpnService = {
  id: 101,
  organization_id: 1,
  created_by_user_id: 10,
  name: "VPN Access",
  description: "Request secure remote access.",
  is_active: true,
  created_at: "2026-07-21T08:00:00Z",
  updated_at: "2026-07-21T08:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("IT service catalog", () => {
  it("lets an organization admin create and disable catalog items", async () => {
    const adminOrganization = { ...organizations[0], role: "admin" };
    const createdService = {
      ...vpnService,
      id: 102,
      name: "Laptop Replacement",
      description: "Replace a damaged company laptop.",
    };
    const inactiveService = {
      ...vpnService,
      id: 100,
      name: "Archived Access",
      is_active: false,
    };
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      const method = options?.method || "GET";
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 10, username: "admin" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [adminOrganization] }),
        );
      }
      if (
        input.endsWith(
          "/service-catalog/items?limit=100&include_inactive=true",
        )
      ) {
        return Promise.resolve(
          jsonResponse({
            items: [inactiveService, vpnService],
            pagination: { offset: 0, limit: 100, total: 2, returned: 2 },
          }),
        );
      }
      if (input.endsWith("/service-catalog/items") && method === "POST") {
        return Promise.resolve(jsonResponse(createdService, 201));
      }
      if (
        input.endsWith("/service-catalog/items/102") &&
        method === "PATCH"
      ) {
        return Promise.resolve(
          jsonResponse({ ...createdService, is_active: false }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderCatalogPage();

    expect(await screen.findAllByText("VPN Access")).toHaveLength(2);
    expect(screen.getByLabelText("服务项目")).toHaveValue("101");
    fireEvent.change(screen.getByLabelText("服务名称"), {
      target: { value: "Laptop Replacement" },
    });
    fireEvent.change(screen.getByLabelText("服务说明"), {
      target: { value: "Replace a damaged company laptop." },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建服务项目" }));

    expect(await screen.findAllByText("Laptop Replacement")).toHaveLength(2);
    fireEvent.click(
      screen.getByRole("button", { name: "停用 Laptop Replacement" }),
    );
    await waitFor(() => {
      expect(screen.getAllByText("已停用")).toHaveLength(2);
    });

    const createCall = fetchMock.mock.calls.find(
      ([url, options]) =>
        typeof url === "string" &&
        url.endsWith("/service-catalog/items") &&
        options?.method === "POST",
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      name: "Laptop Replacement",
      description: "Replace a damaged company laptop.",
    });
    const updateCall = fetchMock.mock.calls.find(
      ([url, options]) =>
        typeof url === "string" &&
        url.endsWith("/service-catalog/items/102") &&
        options?.method === "PATCH",
    );
    expect(JSON.parse(String(updateCall?.[1]?.body))).toEqual({
      is_active: false,
    });
  });

  it("lists active services and creates a pending service request", async () => {
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      const method = options?.method || "GET";
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organizations[0]] }),
        );
      }
      if (input.endsWith("/service-catalog/items?limit=100")) {
        return Promise.resolve(
          jsonResponse({
            items: [vpnService],
            pagination: { offset: 0, limit: 100, total: 1, returned: 1 },
          }),
        );
      }
      if (input.endsWith("/service-requests") && method === "POST") {
        return Promise.resolve(
          jsonResponse(
            {
              id: 501,
              organization_id: 1,
              requester_user_id: 20,
              service_catalog_item_id: 101,
              title: "Remote work VPN",
              description: "I need access for the customer support rotation.",
              status: "pending",
              decided_by_user_id: null,
              decision_reason: null,
              created_at: "2026-07-21T08:10:00Z",
              updated_at: "2026-07-21T08:10:00Z",
              decided_at: null,
            },
            201,
          ),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderCatalogPage();

    expect(await screen.findByText("VPN Access")).toBeInTheDocument();
    expect(screen.queryByLabelText("服务名称")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "申请 VPN Access" }),
    );
    fireEvent.change(screen.getByLabelText("申请标题"), {
      target: { value: "Remote work VPN" },
    });
    fireEvent.change(screen.getByLabelText("申请说明"), {
      target: { value: "I need access for the customer support rotation." },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交申请" }));

    expect(await screen.findByText("申请 #501 已提交")).toBeInTheDocument();
    expect(screen.getByText("待审批")).toBeInTheDocument();

    const createCall = fetchMock.mock.calls.find(
      ([url, options]) =>
        typeof url === "string" &&
        url.endsWith("/service-requests") &&
        options?.method === "POST",
    );
    expect(new Headers(createCall?.[1]?.headers).get("X-Organization-ID")).toBe(
      "1",
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      service_catalog_item_id: 101,
      title: "Remote work VPN",
      description: "I need access for the customer support rotation.",
    });
  });

  it("reloads the active-only catalog and clears form state after an organization switch", async () => {
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations }));
      }
      if (input.endsWith("/service-catalog/items?limit=100")) {
        const organizationId = new Headers(options?.headers).get(
          "X-Organization-ID",
        );
        const items =
          organizationId === "2"
            ? [
                {
                  ...vpnService,
                  id: 202,
                  organization_id: 2,
                  name: "Expense System Access",
                },
              ]
            : [vpnService];
        return Promise.resolve(
          jsonResponse({
            items,
            pagination: { offset: 0, limit: 100, total: 1, returned: 1 },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderCatalogPage();

    expect(await screen.findByText("VPN Access")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("申请标题"), {
      target: { value: "This must not cross organizations" },
    });
    fireEvent.change(screen.getByLabelText("当前组织"), {
      target: { value: "2" },
    });

    expect(
      await screen.findByText("Expense System Access"),
    ).toBeInTheDocument();
    expect(screen.queryByText("VPN Access")).not.toBeInTheDocument();
    expect(screen.getByLabelText("申请标题")).toHaveValue("");
    await waitFor(() => {
      const catalogCalls = fetchMock.mock.calls.filter(
        ([url]) =>
          typeof url === "string" &&
          url.endsWith("/service-catalog/items?limit=100"),
      );
      const lastHeaders = new Headers(catalogCalls.at(-1)?.[1]?.headers);
      expect(lastHeaders.get("X-Organization-ID")).toBe("2");
    });
  });

  it("does not show a request form when there are no active services", async () => {
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organizations[0]] }),
        );
      }
      if (input.endsWith("/service-catalog/items?limit=100")) {
        return Promise.resolve(
          jsonResponse({
            items: [],
            pagination: { offset: 0, limit: 100, total: 0, returned: 0 },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderCatalogPage();

    expect(
      await screen.findByText("当前组织没有可申请的 IT 服务"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("申请标题")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "提交申请" }),
    ).not.toBeInTheDocument();
  });
});
