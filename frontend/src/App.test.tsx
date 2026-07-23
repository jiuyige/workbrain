import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";

import App from "./App";
import { getAccessToken, setAuthSession } from "./auth/session";

function renderApp(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <App />
    </MemoryRouter>,
  );
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("application authentication", () => {
  it("redirects an unauthenticated visitor to login", () => {
    renderApp("/");

    expect(
      screen.getByRole("heading", { name: "登录 WorkBrain" }),
    ).toBeInTheDocument();
  });

  it("logs in, loads the current user and returns to the protected page", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "signed-jwt", token_type: "bearer" }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: 7, username: "alice" }));
    vi.stubGlobal("fetch", fetchMock);
    renderApp("/knowledge-bases");

    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "correct-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(
      await screen.findByRole("heading", { name: "企业知识库" }),
    ).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(getAccessToken()).toBe("signed-jwt");
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/users/login",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/users/me",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
  });

  it("restores the current user then logs out", async () => {
    setAuthSession("persisted-jwt");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ id: 9, username: "bob" })),
    );
    renderApp("/");

    expect(await screen.findByText("bob")).toBeInTheDocument();
    expect(
      screen.getByText(
        "请从主导航进入知识库、IT 服务或审批页面。",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("业务功能将在对应学习日接入"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));

    expect(
      screen.getByRole("heading", { name: "登录 WorkBrain" }),
    ).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
  });

  it("keeps the visitor logged out when credentials are invalid", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "AUTHENTICATION_REQUIRED",
            message: "invalid username or password",
            request_id: "login-failed",
          },
          401,
        ),
      ),
    );
    renderApp("/login");

    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "wrong-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "用户名或密码错误。",
    );
    expect(getAccessToken()).toBeNull();
  });

  it("registers a user and returns to login with a success message", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ message: "register success", id: 11, username: "new-user" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    renderApp("/register");

    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "new-user" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "new-password" },
    });
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "new-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    expect(
      await screen.findByText("注册成功，请使用新账号登录。"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "登录 WorkBrain" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/users/register",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("rejects mismatched registration passwords before calling the API", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderApp("/register");

    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "new-user" },
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "first-password" },
    });
    fireEvent.change(screen.getByLabelText("确认密码"), {
      target: { value: "different-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "两次输入的密码不一致。",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("clears an invalid persisted session and shows login", async () => {
    setAuthSession("expired-jwt");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: "AUTHENTICATION_REQUIRED",
            message: "could not validate credentials",
            request_id: "expired-request",
          },
          401,
        ),
      ),
    );
    renderApp("/");

    expect(
      await screen.findByRole("heading", { name: "登录 WorkBrain" }),
    ).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
  });

  it("ends an active session when a later API request returns 401", async () => {
    setAuthSession("soon-expired-jwt");
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 9, username: "bob" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({
            organizations: [
              {
                id: 1,
                name: "Platform Team",
                slug: "platform-team",
                role: "member",
                created_at: "2026-07-21T08:00:00Z",
              },
            ],
          }),
        );
      }
      if (input.endsWith("/service-catalog/items?limit=100")) {
        return Promise.resolve(
          jsonResponse(
            {
              code: "AUTHENTICATION_REQUIRED",
              message: "could not validate credentials",
              request_id: "expired-later",
            },
            401,
          ),
        );
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApp("/service-catalog");

    expect(
      await screen.findByRole("heading", { name: "登录 WorkBrain" }),
    ).toBeInTheDocument();
    expect(screen.getByText("登录已过期，请重新登录。"))
      .toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
  });

  it("opens and closes the compact navigation without losing routing", async () => {
    setAuthSession("navigation-jwt");
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/users/me")) {
        return Promise.resolve(jsonResponse({ id: 9, username: "bob" }));
      }
      if (input.endsWith("/organizations")) {
        return Promise.resolve(
          jsonResponse({
            organizations: [
              {
                id: 1,
                name: "Platform Team",
                slug: "platform-team",
                role: "member",
                created_at: "2026-07-21T08:00:00Z",
              },
            ],
          }),
        );
      }
      if (input.endsWith("/knowledge-bases")) {
        return Promise.resolve(jsonResponse({ knowledge_bases: [] }));
      }
      throw new Error(`unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderApp("/");

    const menuButton = await screen.findByRole("button", {
      name: "打开导航",
    });
    expect(menuButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("navigation", { name: "主导航" }))
      .not.toHaveClass("open");

    fireEvent.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    expect(menuButton).toHaveAccessibleName("关闭导航");
    expect(screen.getByRole("navigation", { name: "主导航" }))
      .toHaveClass("open");

    fireEvent.click(screen.getByRole("link", { name: "企业知识库" }));
    expect(
      await screen.findByRole("heading", { name: "企业知识库" }),
    ).toBeInTheDocument();
    expect(menuButton).toHaveAttribute("aria-expanded", "false");
  });
});
