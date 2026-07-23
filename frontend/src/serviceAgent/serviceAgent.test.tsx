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

function renderServiceAgentPage() {
  setAuthSession("service-agent-jwt");
  setActiveOrganizationId(1);
  return render(
    <MemoryRouter initialEntries={["/service-agent"]}>
      <App />
    </MemoryRouter>,
  );
}

const organization = {
  id: 1,
  name: "Platform Team",
  slug: "platform-team",
  role: "member",
  created_at: "2026-07-21T08:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("IT service agent conversation", () => {
  it("shows a confirmation card and creates only after explicit confirmation", async () => {
    const fetchMock = vi.fn((input: string, options?: RequestInit) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/assistant/service-tools")) {
        expect(options?.method).toBe("POST");
        expect(new Headers(options?.headers).get("X-Organization-ID")).toBe(
          "1",
        );
        expect(JSON.parse(String(options?.body)).message).toContain(
          "帮我申请 VPN",
        );
        return Promise.resolve(
          jsonResponse({
            action: "confirm_service_request",
            reply: "信息已完整，请确认申请内容。",
            result: {
              requires_confirmation: true,
              confirmation_token: "confirmation-token-with-enough-length",
              service: { id: 101, name: "VPN Access" },
              title: "Need VPN access",
              description: "Required for remote support.",
            },
          }),
        );
      }
      if (input.endsWith("/assistant/service-tools/confirm")) {
        expect(options?.method).toBe("POST");
        expect(new Headers(options?.headers).get("X-Organization-ID")).toBe(
          "1",
        );
        expect(JSON.parse(String(options?.body))).toEqual({
          confirmation_token: "confirmation-token-with-enough-length",
        });
        return Promise.resolve(
          jsonResponse({
            action: "create_service_request",
            reply: "申请单已创建，当前状态为待审批。",
            result: {
              created: true,
              service_request: {
                id: 601,
                organization_id: 1,
                requester_user_id: 20,
                service_catalog_item_id: 101,
                title: "Need VPN access",
                description: "Required for remote support.",
                status: "pending",
                decided_by_user_id: null,
                decision_reason: null,
                created_at: "2026-07-21T10:00:00Z",
                updated_at: "2026-07-21T10:00:00Z",
                decided_at: null,
              },
            },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderServiceAgentPage();

    const input = await screen.findByLabelText("描述你的 IT 服务需求");
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: "帮我申请 VPN" } });
    fireEvent.click(screen.getByRole("button", { name: "发送给服务助手" }));

    expect(await screen.findByText("信息已完整，请确认申请内容。"))
      .toBeInTheDocument();
    expect(screen.getByText("VPN Access")).toBeInTheDocument();
    expect(screen.getByText("Need VPN access")).toBeInTheDocument();
    expect(screen.getByText("Required for remote support.")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([url]) =>
          typeof url === "string" && url.endsWith("/service-tools/confirm"),
      ),
    ).toHaveLength(0);

    fireEvent.click(
      screen.getByRole("button", { name: "确认创建申请" }),
    );

    expect(await screen.findByText("申请 #601 已创建")).toBeInTheDocument();
    expect(screen.getByText("待审批")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "确认创建申请" }),
    ).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([url]) =>
          typeof url === "string" && url.endsWith("/service-tools/confirm"),
      ),
    ).toHaveLength(1);
  });

  it("renders missing fields and candidate services without confirming", async () => {
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/assistant/service-tools")) {
        return Promise.resolve(
          jsonResponse({
            action: "request_service_information",
            reply: "请补充服务项目和申请说明。",
            result: {
              missing_fields: ["service_catalog_item", "description"],
              candidates: [
                { id: 101, name: "VPN Access", description: "Remote access" },
                { id: 102, name: "Laptop Repair", description: "Device help" },
              ],
            },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderServiceAgentPage();

    const input = await screen.findByLabelText("描述你的 IT 服务需求");
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: "我需要 IT 帮助" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(await screen.findByText("请补充服务项目和申请说明。"))
      .toBeInTheDocument();
    expect(screen.getByText("服务项目")).toBeInTheDocument();
    expect(screen.getByText("申请说明")).toBeInTheDocument();
    expect(screen.getByText("VPN Access")).toBeInTheDocument();
    expect(screen.getByText("Laptop Repair")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "确认创建申请" }),
    ).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([url]) =>
          typeof url === "string" && url.endsWith("/service-tools/confirm"),
      ),
    ).toBe(false);
  });

  it("clears confirmation data when the active organization changes", async () => {
    const organizations = [
      organization,
      { ...organization, id: 2, name: "Finance Team", slug: "finance-team" },
    ];
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations }));
      }
      if (input.endsWith("/assistant/service-tools")) {
        return Promise.resolve(
          jsonResponse({
            action: "confirm_service_request",
            reply: "请确认申请。",
            result: {
              requires_confirmation: true,
              confirmation_token: "confirmation-token-with-enough-length",
              service: { id: 101, name: "VPN Access" },
              title: "Need VPN",
              description: "Remote work",
            },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderServiceAgentPage();

    const input = await screen.findByLabelText("描述你的 IT 服务需求");
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: "申请 VPN" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(await screen.findByText("Need VPN")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("当前组织"), {
      target: { value: "2" },
    });

    await waitFor(() => {
      expect(screen.queryByText("Need VPN")).not.toBeInTheDocument();
    });
    expect(screen.getByText("向 Finance Team 的服务助手发起申请"))
      .toBeInTheDocument();
  });

  it("keeps failed input available and explains a forbidden response", async () => {
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/assistant/service-tools")) {
        return Promise.resolve(
          jsonResponse(
            {
              code: "FORBIDDEN",
              message: "organization access denied",
              request_id: "forbidden-agent",
            },
            403,
          ),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderServiceAgentPage();

    const input = await screen.findByLabelText("描述你的 IT 服务需求");
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: "帮我申请数据库权限" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "你没有执行此操作的权限。",
    );
    expect(input).toHaveValue("帮我申请数据库权限");
    expect(screen.getByRole("button", { name: "发送给服务助手" }))
      .toBeEnabled();
  });

  it("dismisses a confirmation without calling the write endpoint", async () => {
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/assistant/service-tools")) {
        return Promise.resolve(
          jsonResponse({
            action: "confirm_service_request",
            reply: "请确认申请。",
            result: {
              requires_confirmation: true,
              confirmation_token: "confirmation-token-with-enough-length",
              service: { id: 101, name: "VPN Access" },
              title: "Need VPN",
              description: "Remote work",
            },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderServiceAgentPage();

    const input = await screen.findByLabelText("描述你的 IT 服务需求");
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: "申请 VPN" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(
      await screen.findByRole("button", { name: "确认创建申请" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "暂不提交" }));

    expect(
      screen.queryByRole("button", { name: "确认创建申请" }),
    ).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([url]) =>
          typeof url === "string" && url.endsWith("/service-tools/confirm"),
      ),
    ).toBe(false);
  });

  it("keeps the confirmation available when creation fails, then allows retry", async () => {
    let confirmationAttempts = 0;
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 20, username: "requester" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(jsonResponse({ organizations: [organization] }));
      }
      if (input.endsWith("/assistant/service-tools")) {
        return Promise.resolve(
          jsonResponse({
            action: "confirm_service_request",
            reply: "请确认申请。",
            result: {
              requires_confirmation: true,
              confirmation_token: "confirmation-token-with-enough-length",
              service: { id: 101, name: "VPN Access" },
              title: "Need VPN",
              description: "Remote work",
            },
          }),
        );
      }
      if (input.endsWith("/assistant/service-tools/confirm")) {
        confirmationAttempts += 1;
        if (confirmationAttempts === 1) {
          return Promise.resolve(
            jsonResponse(
              {
                code: "CONFLICT",
                message: "service catalog item is no longer available",
                request_id: "service-disabled",
              },
              409,
            ),
          );
        }
        return Promise.resolve(
          jsonResponse({
            action: "create_service_request",
            reply: "申请单已创建，当前状态为待审批。",
            result: {
              created: true,
              service_request: {
                id: 602,
                organization_id: 1,
                requester_user_id: 20,
                service_catalog_item_id: 101,
                title: "Need VPN",
                description: "Remote work",
                status: "pending",
                decided_by_user_id: null,
                decision_reason: null,
                created_at: "2026-07-21T10:00:00Z",
                updated_at: "2026-07-21T10:00:00Z",
                decided_at: null,
              },
            },
          }),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderServiceAgentPage();

    const input = await screen.findByLabelText("描述你的 IT 服务需求");
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: "申请 VPN" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    const confirmButton = await screen.findByRole("button", {
      name: "确认创建申请",
    });

    fireEvent.click(confirmButton);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "service catalog item is no longer available",
    );
    expect(confirmButton).toBeEnabled();

    fireEvent.click(confirmButton);
    expect(await screen.findByText("申请 #602 已创建")).toBeInTheDocument();
    expect(confirmationAttempts).toBe(2);
  });
});
