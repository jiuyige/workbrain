import { ApiError } from "../api/client";

export function getAuthErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "请求失败，请稍后重试。";
  }

  if (error.status === 401) {
    return "用户名或密码错误。";
  }
  if (error.message === "username already exists") {
    return "用户名已存在，请更换后重试。";
  }

  return error.message;
}
