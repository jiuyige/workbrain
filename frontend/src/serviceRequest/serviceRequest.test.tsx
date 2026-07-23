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

function renderRequestsPage() {
  setAuthSession("service-request-jwt");
  setActiveOrganizationId(1);
  return render(
    <MemoryRouter initialEntries={["/service-requests"]}>
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

const pendingRequest = {
  id: 501,
  organization_id: 1,
  requester_user_id: 20,
  service_catalog_item_id: 101,
  title: "Remote work VPN",
  description: "VPN access is required for the support rotation.",
  status: "pending",
  decided_by_user_id: null,
  decision_reason: null,
  created_at: "2026-07-21T08:10:00Z",
  updated_at: "2026-07-21T08:10:00Z",
  decided_at: null,
};

const approvedRequest = {
  ...pendingRequest,
  id: 502,
  title: "Laptop replacement",
  status: "approved",
  decided_by_user_id: 30,
  updated_at: "2026-07-21T09:00:00Z",
  decided_at: "2026-07-21T09:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("service request tracking", () => {
  it("lists a request and shows its details and audit timeline", async () => {
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organizations[0]] }),
        );
      }
      if (input.endsWith("/service-requests?limit=100")) {
        return Promise.resolve(
          jsonResponse({
            requests: [pendingRequest],
            pagination: { offset: 0, limit: 100, total: 1, returned: 1 },
          }),
        );
      }
      if (input.endsWith("/service-requests/501/events")) {
        expect(new Headers(options?.headers).get("X-Organization-ID")).toBe(
          "1",
        );
        return Promise.resolve(
          jsonResponse({
            service_request_id: 501,
            events: [
              {
                id: 801,
                actor_user_id: 20,
                action: "create",
                from_status: null,
                to_status: "pending",
                reason: null,
                created_at: "2026-07-21T08:10:00Z",
              },
            ],
          }),
        );
      }
      if (input.endsWith("/service-requests/501")) {
        expect(new Headers(options?.headers).get("X-Organization-ID")).toBe(
          "1",
        );
        return Promise.resolve(jsonResponse(pendingRequest));
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRequestsPage();

    expect(await screen.findByText("Remote work VPN")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "查看申请 #501" }),
    );

    expect(
      await screen.findByText("VPN access is required for the support rotation."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("服务项目 #101")).toHaveLength(2);
    expect(screen.getByText("创建申请")).toBeInTheDocument();
    expect(screen.getByText("操作者 #20")).toBeInTheDocument();

    const detailCall = fetchMock.mock.calls.find(
      ([url]) =>
        typeof url === "string" && url.endsWith("/service-requests/501"),
    );
    const eventCall = fetchMock.mock.calls.find(
      ([url]) =>
        typeof url === "string" &&
        url.endsWith("/service-requests/501/events"),
    );
    expect(new Headers(detailCall?.[1]?.headers).get("X-Organization-ID")).toBe(
      "1",
    );
    expect(new Headers(eventCall?.[1]?.headers).get("X-Organization-ID")).toBe(
      "1",
    );
  });

  it("reloads requests when filtering by status", async () => {
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organizations[0]] }),
        );
      }
      if (input.endsWith("/service-requests?limit=100")) {
        return Promise.resolve(
          jsonResponse({
            requests: [pendingRequest],
            pagination: { offset: 0, limit: 100, total: 1, returned: 1 },
          }),
        );
      }
      if (input.endsWith("/service-requests?limit=100&status=approved")) {
        return Promise.resolve(
          jsonResponse({
            requests: [approvedRequest],
            pagination: { offset: 0, limit: 100, total: 1, returned: 1 },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRequestsPage();

    expect(await screen.findByText("Remote work VPN")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("申请状态"), {
      target: { value: "approved" },
    });

    expect(await screen.findByText("Laptop replacement")).toBeInTheDocument();
    expect(screen.getAllByText("已批准")).toHaveLength(2);
    expect(screen.queryByText("Remote work VPN")).not.toBeInTheDocument();
  });

  it("clears request details and reloads data after an organization switch", async () => {
    const secondRequest = {
      ...pendingRequest,
      id: 601,
      organization_id: 2,
      service_catalog_item_id: 202,
      title: "Expense system access",
      description: "Finance access is needed.",
    };
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations }));
      }
      if (input.endsWith("/service-requests?limit=100")) {
        const organizationId = new Headers(options?.headers).get(
          "X-Organization-ID",
        );
        const requests = organizationId === "2" ? [secondRequest] : [pendingRequest];
        return Promise.resolve(
          jsonResponse({
            requests,
            pagination: { offset: 0, limit: 100, total: 1, returned: 1 },
          }),
        );
      }
      if (input.endsWith("/service-requests/501/events")) {
        return Promise.resolve(
          jsonResponse({ service_request_id: 501, events: [] }),
        );
      }
      if (input.endsWith("/service-requests/501")) {
        return Promise.resolve(jsonResponse(pendingRequest));
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRequestsPage();

    expect(await screen.findByText("Remote work VPN")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "查看申请 #501" }),
    );
    expect(
      await screen.findByText("VPN access is required for the support rotation."),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("当前组织"), {
      target: { value: "2" },
    });

    expect(await screen.findByText("Expense system access")).toBeInTheDocument();
    expect(screen.queryByText("Remote work VPN")).not.toBeInTheDocument();
    expect(
      screen.queryByText("VPN access is required for the support rotation."),
    ).not.toBeInTheDocument();
    await waitFor(() => {
      const listCalls = fetchMock.mock.calls.filter(
        ([url]) =>
          typeof url === "string" &&
          url.endsWith("/service-requests?limit=100"),
      );
      const lastHeaders = new Headers(listCalls.at(-1)?.[1]?.headers);
      expect(lastHeaders.get("X-Organization-ID")).toBe("2");
    });
  });
});
