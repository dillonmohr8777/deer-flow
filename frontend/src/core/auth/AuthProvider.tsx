"use client";

import { useRouter, usePathname } from "next/navigation";
import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactNode,
} from "react";

import { queryClient } from "@/components/query-client-provider";

import { isStaticWebsiteOnly } from "../static-mode";

import { isClientUser, isRoleUnresolved } from "./roles";
import { type User, buildLoginUrl, userSchema } from "./types";

// Re-export for consumers
export type { User };

/**
 * Authentication context provided to consuming components
 */
interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isLoggingOut: boolean;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  applyUser: (user: User | null) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

interface AuthProviderProps {
  children: ReactNode;
  initialUser: User | null;
}

/**
 * AuthProvider - Unified authentication context for the application
 *
 * Per RFC-001:
 * - Only holds display information (user), never JWT or tokens
 * - initialUser comes from server-side guard, avoiding client flicker
 * - Provides logout and refresh capabilities
 */
export function AuthProvider({ children, initialUser }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(initialUser);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const logoutStartedRef = useRef(false);
  const currentUserRef = useRef(initialUser);
  const initialUserRef = useRef(initialUser);
  const authGenerationRef = useRef(0);
  const refreshRequestIdRef = useRef(0);
  const router = useRouter();
  const pathname = usePathname();
  const staticMode = isStaticWebsiteOnly();

  const isAuthenticated = user !== null;

  const invalidateAuthRequests = useCallback(() => {
    authGenerationRef.current += 1;
    refreshRequestIdRef.current += 1;
  }, []);

  /**
   * Apply a confirmed user, fencing older refreshes and clearing cached data
   * on identity changes. Ignore recovery responses once logout has started.
   */
  const applyUser = useCallback(
    (next: User | null) => {
      if (logoutStartedRef.current) return;
      // Callers such as the offline banner already hold an authoritative user
      // response. Fence any older /auth/me request before applying it.
      invalidateAuthRequests();
      if (currentUserRef.current?.id !== next?.id) {
        // Query keys are not uniformly account-scoped. Remove every prior
        // identity's response before publishing a different user to consumers.
        queryClient.clear();
      }
      currentUserRef.current = next;
      setUser(next);
      setIsLoading(false);
    },
    [invalidateAuthRequests],
  );

  // Layout sync keeps a newly server-confirmed identity from being hidden by
  // the provider's initial useState value during client-side route updates.
  // It also fences a refresh started under the previous server identity.
  useIsomorphicLayoutEffect(() => {
    if (initialUserRef.current === initialUser) return;
    initialUserRef.current = initialUser;
    applyUser(initialUser);
  }, [initialUser, applyUser]);

  /**
   * Fetch current user from FastAPI
   * Used when initialUser might be stale (e.g., after tab was inactive)
   */
  const refreshUser = useCallback(async () => {
    if (staticMode || logoutStartedRef.current) return;

    const requestId = ++refreshRequestIdRef.current;
    const authGeneration = authGenerationRef.current;
    const isCurrentRequest = () =>
      refreshRequestIdRef.current === requestId &&
      authGenerationRef.current === authGeneration;

    try {
      setIsLoading(true);
      const res = await fetch("/api/v1/auth/me", {
        credentials: "include",
      });

      if (res.ok) {
        const parsed = userSchema.safeParse(await res.json());
        if (parsed.success && isCurrentRequest()) {
          applyUser(parsed.data);
        }
      } else if (res.status === 401) {
        // Session expired or invalid
        if (isCurrentRequest()) {
          applyUser(null);
          // Redirect to login if on a protected route
          if (pathname?.startsWith("/workspace")) {
            router.push(buildLoginUrl(`${pathname}${window.location.search}`));
          }
        }
      }
    } catch (err) {
      // A transport or parse failure does not establish that the session is
      // invalid. Keep the last confirmed user; only a 401 clears it.
      if (isCurrentRequest()) {
        console.error("Failed to refresh user:", err);
      }
    } finally {
      if (isCurrentRequest()) {
        setIsLoading(false);
      }
    }
  }, [staticMode, pathname, router, applyUser]);

  /**
   * Logout - call FastAPI logout endpoint and clear local state
   * Per RFC-001: Immediately clear local state, don't wait for server confirmation
   *
   * When the gateway is unreachable the fetch silently fails — the SPA
   * router.push("/") would leave the user on "/" still holding stale
   * React state and any in-flight SSE / fetch / query subscriptions.
   * We therefore fall back to a hard navigation (window.location.href),
   * which discards all client state the same way the legacy form-POST
   * logout used to.
   */
  const logout = useCallback(async () => {
    // Fence recovery without rebuilding mounted queries under a live session.
    // The workspace/auth layout's provider unmounts on navigation to home.
    logoutStartedRef.current = true;
    invalidateAuthRequests();
    currentUserRef.current = null;
    setUser(null);
    setIsLoading(false);
    setIsLoggingOut(true);

    if (staticMode) {
      queryClient.clear();
      router.push("/");
      return;
    }

    let logoutFailed = false;
    try {
      const res = await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) logoutFailed = true;
    } catch (err) {
      console.error("Logout request failed:", err);
      logoutFailed = true;
    }

    if (logoutFailed && typeof window !== "undefined") {
      // Hard navigation ensures every in-flight subscription is torn down,
      // matching the legacy form-POST logout behaviour during a gateway outage.
      window.location.href = "/";
      return;
    }

    // Drop every cached response (staff-only Team and Academy data among
    // them) before the soft navigation keeps this tab's query cache alive.
    queryClient.clear();
    // Redirect to home page
    router.push("/");
  }, [staticMode, router, invalidateAuthRequests]);

  /**
   * Handle visibility change - refresh user when tab becomes visible again.
   * Throttled to at most once per 60 s to avoid spamming the backend on rapid tab switches.
   */
  const lastCheckRef = React.useRef(0);

  useEffect(() => {
    if (staticMode) return;

    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible" || user === null) return;
      const now = Date.now();
      if (now - lastCheckRef.current < 60_000) return;
      lastCheckRef.current = now;
      void refreshUser();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [staticMode, user, refreshUser]);

  const value: AuthContextType = {
    user,
    isAuthenticated,
    isLoading,
    isLoggingOut,
    logout,
    refreshUser,
    applyUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Hook to access authentication context
 * Throws if used outside AuthProvider - this is intentional for proper usage
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

/** Whether the signed-in user is an external client (chat with MomoBot Max only). */
export function useIsClient(): boolean {
  return isClientUser(useAuth().user);
}

/**
 * Whether the role is still unknown. Treat it as "maybe a client": render
 * nothing internal until it resolves.
 */
export function useIsRoleUnresolved(): boolean {
  return isRoleUnresolved(useAuth().user, isStaticWebsiteOnly());
}

/**
 * Hook to require authentication - redirects to login if not authenticated
 * Useful for client-side checks in addition to server-side guards
 */
export function useRequireAuth(): AuthContextType {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (isStaticWebsiteOnly()) return;

    // Only redirect if we're sure user is not authenticated (not just loading)
    if (!auth.isLoading && !auth.isLoggingOut && !auth.isAuthenticated) {
      router.push(
        buildLoginUrl(`${pathname || "/workspace"}${window.location.search}`),
      );
    }
  }, [
    auth.isAuthenticated,
    auth.isLoading,
    auth.isLoggingOut,
    router,
    pathname,
  ]);

  return auth;
}
