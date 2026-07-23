import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

import {
  type CurrentUser,
  getCurrentUser,
  loginUser,
  registerUser,
} from "./api";
import {
  AUTH_SESSION_EXPIRED_EVENT,
  clearAuthSession,
  getAccessToken,
  setAuthSession,
} from "./session";

interface AuthContextValue {
  currentUser: CurrentUser | null;
  isLoading: boolean;
  sessionMessage: string;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(() => getAccessToken() !== null);
  const [sessionMessage, setSessionMessage] = useState("");

  useEffect(() => {
    function handleExpiredSession() {
      setCurrentUser(null);
      setIsLoading(false);
      setSessionMessage("登录已过期，请重新登录。");
    }

    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, handleExpiredSession);
    return () => {
      window.removeEventListener(
        AUTH_SESSION_EXPIRED_EVENT,
        handleExpiredSession,
      );
    };
  }, []);

  useEffect(() => {
    if (getAccessToken() === null) {
      return;
    }

    let isActive = true;
    getCurrentUser()
      .then((user) => {
        if (isActive) {
          setCurrentUser(user);
        }
      })
      .catch(() => {
        if (isActive) {
          clearAuthSession();
          setCurrentUser(null);
        }
      })
      .finally(() => {
        if (isActive) {
          setIsLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, []);

  async function login(username: string, password: string): Promise<void> {
    setIsLoading(true);
    setSessionMessage("");
    try {
      const token = await loginUser(username, password);
      setAuthSession(token.access_token);
      const user = await getCurrentUser();
      setCurrentUser(user);
    } catch (error) {
      clearAuthSession();
      setCurrentUser(null);
      throw error;
    } finally {
      setIsLoading(false);
    }
  }

  async function register(username: string, password: string): Promise<void> {
    await registerUser(username, password);
  }

  function logout(): void {
    clearAuthSession();
    setCurrentUser(null);
    setIsLoading(false);
    setSessionMessage("");
  }

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        isLoading,
        sessionMessage,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
