import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

/** Thème clair / sombre, mémorisé dans le navigateur (simple confort, sans importance si perdu). */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem("oddo-theme", theme);
    } catch {
      /* stockage indisponible (navigation privée) : on ignore */
    }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}
