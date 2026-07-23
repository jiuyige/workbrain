import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { getAuthErrorMessage } from "../auth/errorMessage";

interface LoginLocationState {
  from?: { pathname?: string };
  registered?: boolean;
}

export function LoginPage() {
  const { isLoading, login, sessionMessage } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const locationState = location.state as LoginLocationState | null;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage("");
    setIsSubmitting(true);

    try {
      await login(username.trim(), password);
      const destination = locationState?.from?.pathname || "/";
      navigate(destination, { replace: true });
    } catch (error) {
      setErrorMessage(getAuthErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <span className="brand-mark">WB</span>
        <p className="eyebrow">企业知识与 IT 服务助手</p>
        <h1>登录 WorkBrain</h1>
        <p className="auth-description">登录后访问你的组织知识库和服务申请。</p>
        {locationState?.registered && (
          <p className="form-message success" role="status">
            注册成功，请使用新账号登录。
          </p>
        )}
        {sessionMessage && (
          <p className="form-message warning" role="status">
            {sessionMessage}
          </p>
        )}
        {errorMessage && (
          <p className="form-message error" role="alert">
            {errorMessage}
          </p>
        )}
        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            用户名
            <input
              name="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
              disabled={isSubmitting || isLoading}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
              disabled={isSubmitting || isLoading}
            />
          </label>
          <button type="submit" disabled={isSubmitting || isLoading}>
            {isSubmitting ? "正在登录…" : "登录"}
          </button>
        </form>
        <p className="auth-switch">
          还没有账号？<Link to="/register">创建账号</Link>
        </p>
      </section>
    </main>
  );
}
