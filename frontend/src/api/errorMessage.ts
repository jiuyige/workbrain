import { ApiError } from "./client";

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "登录已过期，请重新登录。";
    }
    if (error.status === 403) {
      return "你没有执行此操作的权限。";
    }
    if (error.status === 404) {
      return "请求的资源不存在或你无权访问。";
    }
    return error.message;
  }
  if (error instanceof TypeError) {
    return "无法连接服务器，请检查网络后重试。";
  }
  return "请求失败，请稍后重试。";
}
