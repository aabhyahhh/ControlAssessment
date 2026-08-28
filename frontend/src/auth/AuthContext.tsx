import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import * as authService from "../services/authService";
import { clearToken, getToken, setToken } from "../services/api";
import type { User } from "../types";

interface AuthContextValue {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setIsLoading(false);
      return;
    }
    authService
      .me()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await authService.login(email, password);
    setToken(access_token);
    const currentUser = await authService.me();
    setUser(currentUser);
  }, []);

  const register = useCallback(async (email: string, password: string, name?: string) => {
    const { access_token } = await authService.register(email, password, name);
    setToken(access_token);
    const currentUser = await authService.me();
    setUser(currentUser);
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, isAuthenticated: !!user, isLoading, login, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
