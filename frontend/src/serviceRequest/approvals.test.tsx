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

function renderApprovalsPage() {
  setAuthSession("approval-jwt");
  setActiveOrganizationId(1);
  return render(
    <MemoryRouter initialEntries={["/approvals"]}>
      <App />
    </MemoryRouter>,
  );
}

function organization(role: "member" | "approver" | "admin") {
  return {
    id: 1,
    name: "Platform Team",
    slug: "platform-team",
    role,
    created_at: "2026-07-21T08:00:00Z",
  };
}

const firstRequest = {
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

const secondRequest = {
  ...firstRequest,
  id: 502,
  requester_user_id: 21,
  title: "Laptop replacement",
  description: "The current device can no longer run required tools.",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("service request approvals", () => {
  it("does not load organization requests for an ordinary member", async () => {
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "member" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organization("member")] }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApprovalsPage();

    expect(
      await screen.findByText("只有审批人或管理员可以处理服务申请。"),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([url]) =>
          typeof url === "string" && url.includes("/service-requests?"),
      ),
    ).toBe(false);
  });

  it("lets an approver approve and reject pending requests", async () => {
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 30, username: "approver" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organization("approver")] }),
        );
      }
      if (input.endsWith("/service-requests?limit=100&status=pending")) {
        expect(new Headers(options?.headers).get("X-Organization-ID")).toBe(
          "1",
        );
        return Promise.resolve(
          jsonResponse({ requests: [firstRequest, secondRequest] }),
        );
      }
      if (input.endsWith("/service-requests/501/approve")) {
        expect(options?.method).toBe("POST");
        expect(new Headers(options?.headers).get("X-Organization-ID")).toBe(
          "1",
        );
        return Promise.resolve(
          jsonResponse({ ...firstRequest, status: "approved" }),
        );
      }
      if (input.endsWith("/service-requests/502/reject")) {
        expect(options?.method).toBe("POST");
        expect(JSON.parse(String(options?.body))).toEqual({
          reason: "Missing manager approval.",
        });
        expect(new Headers(options?.headers).get("X-Organization-ID")).toBe(
          "1",
        );
        return Promise.resolve(
          jsonResponse({
            ...secondRequest,
            status: "rejected",
            decision_reason: "Missing manager approval.",
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApprovalsPage();

    expect(await screen.findByText("Remote work VPN")).toBeInTheDocument();
    expect(screen.getByText("Laptop replacement")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "批准申请 #501" }),
    );
    expect(await screen.findByText("申请 #501 已批准。"))
      .toBeInTheDocument();
    expect(screen.queryByText("Remote work VPN")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "拒绝申请 #502" }),
    );
    fireEvent.change(screen.getByLabelText("拒绝原因"), {
      target: { value: "Missing manager approval." },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认拒绝" }));

    expect(await screen.findByText("申请 #502 已拒绝。"))
      .toBeInTheDocument();
    expect(screen.queryByText("Laptop replacement")).not.toBeInTheDocument();
  });

  it("does not offer approval actions for the approver's own request", async () => {
    const ownRequest = { ...firstRequest, requester_user_id: 30 };
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 30, username: "approver" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organization("approver")] }),
        );
      }
      if (input.endsWith("/service-requests?limit=100&status=pending")) {
        return Promise.resolve(jsonResponse({ requests: [ownRequest] }));
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApprovalsPage();

    expect(
      await screen.findByText("不能审批自己提交的申请。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "批准申请 #501" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "拒绝申请 #501" }),
    ).not.toBeInTheDocument();

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(3);
    });
  });

  it("keeps a request actionable when the backend rejects an approval", async () => {
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 30, username: "approver" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organization("approver")] }),
        );
      }
      if (input.endsWith("/service-requests?limit=100&status=pending")) {
        return Promise.resolve(jsonResponse({ requests: [firstRequest] }));
      }
      if (input.endsWith("/service-requests/501/approve")) {
        return Promise.resolve(
          jsonResponse(
            {
              code: "CONFLICT",
              message: "service request is already finished",
              request_id: "approval-conflict",
            },
            409,
          ),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApprovalsPage();

    expect(await screen.findByText("Remote work VPN")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "批准申请 #501" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "service request is already finished",
    );
    expect(screen.getByText("Remote work VPN")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批准申请 #501" }))
      .toBeEnabled();
  });

  it("requires a nonblank reason before submitting a rejection", async () => {
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 30, username: "approver" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({ organizations: [organization("approver")] }),
        );
      }
      if (input.endsWith("/service-requests?limit=100&status=pending")) {
        return Promise.resolve(jsonResponse({ requests: [firstRequest] }));
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApprovalsPage();

    expect(await screen.findByText("Remote work VPN")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "拒绝申请 #501" }),
    );
    const submitButton = screen.getByRole("button", { name: "确认拒绝" });
    expect(submitButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("拒绝原因"), {
      target: { value: "   " },
    });
    expect(submitButton).toBeDisabled();
    expect(
      fetchMock.mock.calls.some(
        ([url]) =>
          typeof url === "string" && url.endsWith("/service-requests/501/reject"),
      ),
    ).toBe(false);
  });
});
