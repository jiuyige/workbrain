import { ApiError } from "./client";
import { getApiErrorMessage } from "./errorMessage";

describe("API error messages", () => {
  it.each([
    [401, "登录已过期，请重新登录。"],
    [403, "你没有执行此操作的权限。"],
    [404, "请求的资源不存在或你无权访问。"],
  ])("maps HTTP %i to a safe Chinese message", (status, expected) => {
    const error = new ApiError(
      status,
      "HTTP_ERROR",
      "backend implementation detail",
      "request-123",
    );

    expect(getApiErrorMessage(error)).toBe(expected);
  });

  it("shows a recoverable message for a network failure", () => {
    expect(getApiErrorMessage(new TypeError("Failed to fetch"))).toBe(
      "无法连接服务器，请检查网络后重试。",
    );
  });
});
