// Auth state: who is signed in (httponly cookie, checked via GET /me), plus the
// sign-in / create-account modal that any page can open with openAuthModal().
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import * as api from "./api";

export type AuthMode = "login" | "register";

export interface AuthModalState {
  open: boolean;
  mode: AuthMode;
  reason?: string;
  onSuccess?: (user: api.User) => void;
}

interface AuthState {
  user: api.User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<api.User>;
  register: (body: api.RegisterBody) => Promise<api.User>;
  logout: () => Promise<void>;
  refresh: () => Promise<api.User | null>;
  setUser: (user: api.User | null) => void;
  modal: AuthModalState;
  openAuthModal: (mode?: AuthMode, opts?: { reason?: string; onSuccess?: (user: api.User) => void }) => void;
  closeAuthModal: () => void;
  setAuthMode: (mode: AuthMode) => void;
}

const AuthContext = createContext<AuthState | null>(null);
const CLOSED: AuthModalState = { open: false, mode: "login" };

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<api.User | null>(null);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<AuthModalState>(CLOSED);

  const refresh = useCallback(async () => {
    try {
      const me = await api.getMe();
      setUser(me);
      return me;
    } catch {
      // 401 simply means "signed out".
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Any private call that comes back 401 means the session ended.
  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "config" });
    };
    window.addEventListener(api.UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(api.UNAUTHORIZED_EVENT, onUnauthorized);
  }, [queryClient]);

  const login = useCallback(async (email: string, password: string) => {
    await api.login(email, password);
    const me = await api.getMe();
    setUser(me);
    return me;
  }, []);

  const register = useCallback(async (body: api.RegisterBody) => {
    // The server signs the new user in (sets the cookie) and returns the account.
    const me = await api.register(body);
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "config" });
    }
  }, [queryClient]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login,
      register,
      logout,
      refresh,
      setUser,
      modal,
      openAuthModal: (mode = "login", opts = {}) => setModal({ open: true, mode, ...opts }),
      closeAuthModal: () => setModal(CLOSED),
      setAuthMode: (mode) => setModal((m) => ({ ...m, mode })),
    }),
    [user, loading, login, register, logout, refresh, modal]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
