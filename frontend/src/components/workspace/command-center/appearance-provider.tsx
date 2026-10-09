"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/core/auth/AuthProvider";

import {
  appearanceKey,
  brandMotionAllowed,
  DEFAULT_APPEARANCE,
  parseAppearance,
  type AppearancePreferences,
} from "./appearance-preferences";

type AppearanceContextValue = {
  preferences: AppearancePreferences;
  reducedMotion: boolean;
  visible: boolean;
  /** brandMotionAllowed({ motion: preferences.motion, reducedMotion, visible, inView: true }) */
  motionOn: boolean;
  persistence: "loading" | "local" | "memory";
  canCustomize: boolean;
  update: (patch: Partial<AppearancePreferences>) => void;
  reset: () => void;
};

const AppearanceContext = createContext<AppearanceContextValue>({
  preferences: DEFAULT_APPEARANCE,
  reducedMotion: true,
  visible: false,
  motionOn: false,
  persistence: "loading",
  canCustomize: false,
  update: () => undefined,
  reset: () => undefined,
});

export function useWorkspaceAppearance() {
  return useContext(AppearanceContext);
}

export function WorkspaceAppearanceProvider({
  children,
}: {
  children: ReactNode;
}) {
  const { user } = useAuth();
  return (
    <AccountAppearance key={user?.id ?? "signed-out"} userId={user?.id ?? null}>
      {children}
    </AccountAppearance>
  );
}

function AccountAppearance({
  children,
  userId,
}: {
  children: ReactNode;
  userId: string | null;
}) {
  const [preferences, setPreferences] = useState(DEFAULT_APPEARANCE);
  const currentPreferences = useRef(preferences);
  currentPreferences.current = preferences;
  const [persistence, setPersistence] =
    useState<AppearanceContextValue["persistence"]>("loading");
  const [reducedMotion, setReducedMotion] = useState(true);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const readMotion = () => setReducedMotion(media.matches);
    const readVisibility = () =>
      setVisible(document.visibilityState === "visible");
    readMotion();
    readVisibility();
    media.addEventListener("change", readMotion);
    document.addEventListener("visibilitychange", readVisibility);
    return () => {
      media.removeEventListener("change", readMotion);
      document.removeEventListener("visibilitychange", readVisibility);
    };
  }, []);

  // Dialogs, menus and the mobile sidebar sheet portal to <body>, outside the
  // wrapper below; mirroring the treatment onto <html> lets paper.css reach them.
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.treatment = preferences.treatment;
    return () => {
      delete root.dataset.treatment;
    };
  }, [preferences.treatment]);

  // Same mirroring for the app's one motion switch: components that gate a
  // treatment's decorative animation off a plain CSS selector (future's H1
  // echo) read this instead of recomputing brandMotionAllowed per element.
  const motionOn = brandMotionAllowed({
    motion: preferences.motion,
    reducedMotion,
    visible,
    inView: true,
  });
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.motion = motionOn ? "on" : "off";
    return () => {
      delete root.dataset.motion;
    };
  }, [motionOn]);

  useEffect(() => {
    if (!userId) {
      setPersistence("memory");
      return;
    }
    const key = appearanceKey(userId);
    const read = () => {
      try {
        setPreferences(parseAppearance(window.localStorage.getItem(key)));
        setPersistence("local");
      } catch {
        setPersistence("memory");
      }
    };
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea !== window.localStorage) return;
      if (event.key === key || event.key === null) read();
    };
    read();
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [userId]);

  function update(patch: Partial<AppearancePreferences>) {
    if (!userId || persistence === "loading") return;
    const next = parseAppearance(
      JSON.stringify({ ...currentPreferences.current, ...patch }),
    );
    currentPreferences.current = next;
    setPreferences(next);
    try {
      window.localStorage.setItem(appearanceKey(userId), JSON.stringify(next));
      setPersistence("local");
    } catch {
      setPersistence("memory");
    }
  }

  function reset() {
    if (!userId) return;
    setPreferences({ ...DEFAULT_APPEARANCE });
    try {
      window.localStorage.removeItem(appearanceKey(userId));
      setPersistence("local");
    } catch {
      setPersistence("memory");
    }
  }

  return (
    <AppearanceContext.Provider
      value={{
        preferences,
        reducedMotion,
        visible,
        motionOn,
        persistence,
        canCustomize: Boolean(userId) && persistence !== "loading",
        update,
        reset,
      }}
    >
      {/* display: contents keeps this wrapper out of the layout tree while
          still letting [data-treatment="paper"] descendant rules match.
          data-workspace-shell scopes paper.css's shell tokens to the
          workspace, away from landing, login and invite. */}
      <div
        data-workspace-shell=""
        data-treatment={preferences.treatment}
        data-motion={motionOn ? "on" : "off"}
        style={{ display: "contents" }}
      >
        {children}
      </div>
    </AppearanceContext.Provider>
  );
}
