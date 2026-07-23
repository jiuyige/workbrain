import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { getAuthErrorMessage } from "../auth/errorMessage";

export function RegisterPage() {
  const { currentUser, register } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (currentUser) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage("");

    if (password !== passwordConfirmation) {
      setErrorMessage("两次输入的密码不一致。");
      return;
    }

    setIsSubmitting(true);
    try {
      await register(username.trim(), password);
      navigate("/login", { replace: true, state: { registered: true } });
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
        <p className="eyebrow">创建 WorkBrain 账号</p>
        <h1>注册</h1>
        <p className="auth-description">创建账号后即可登录企业工作台。</p>
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
              disabled={isSubmitting}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              required
              disabled={isSubmitting}
            />
          </label>
          <label>
            确认密码
            <input
              name="password-confirmation"
              type="password"
              value={passwordConfirmation}
              onChange={(event) => setPasswordConfirmation(event.target.value)}
              autoComplete="new-password"
              required
              disabled={isSubmitting}
            />
          </label>
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "正在创建…" : "创建账号"}
          </button>
        </form>
        <p className="auth-switch">
          已有账号？<Link to="/login">返回登录</Link>
        </p>
      </section>
    </main>
  );
}
