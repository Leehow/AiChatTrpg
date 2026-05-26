import { useCallback, useEffect, useState } from "react";
import {
  getStoredToken,
  getStoredUser,
  onAuthChanged,
  type StoredUser,
} from "../api/http";
import { logoutAPI } from "../api/auth";

export type Theme = "warm" | "slate";
const THEME_KEY = "chatrpg.theme";

export function usePathname(): string {
  const [path, setPath] = useState(() =>
    typeof window === "undefined" ? "/" : window.location.pathname
  );
  useEffect(() => {
    const handler = () => setPath(window.location.pathname);
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);
  return path;
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    if (typeof window === "undefined") return "warm";
    const saved = window.localStorage.getItem(THEME_KEY);
    return saved === "slate" ? "slate" : "warm";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);
  const toggle = useCallback(
    () => setTheme((t) => (t === "warm" ? "slate" : "warm")),
    []
  );
  return [theme, toggle];
}

export function useAuthGate(): {
  user: StoredUser | null;
  signIn: () => void;
  signOut: () => void;
} {
  const [user, setUser] = useState<StoredUser | null>(() => {
    if (typeof window === "undefined") return null;
    return getStoredToken() ? getStoredUser() : null;
  });
  useEffect(() => {
    return onAuthChanged(() => {
      setUser(getStoredToken() ? getStoredUser() : null);
    });
  }, []);
  const signIn = useCallback(() => {
    setUser(getStoredUser());
  }, []);
  const signOut = useCallback(() => {
    logoutAPI();
    // onAuthChanged subscriber will reset state.
  }, []);
  return { user, signIn, signOut };
}
