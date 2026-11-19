import { useQuery } from "@tanstack/react-query";
import { getConfig, type AppConfig } from "../api";

const CACHE_KEY = "tradetrack.config.v1";

// Public, non-secret settings only. Lets a returning visitor see plans immediately while a sleeping
// free-tier server wakes up; the live response always replaces it.
function cached(): AppConfig | undefined {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? (JSON.parse(raw) as AppConfig) : undefined;
  } catch {
    return undefined;
  }
}

/** Public app config (plans, limits, which services are configured). Loaded once per visit. */
export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const config = await getConfig();
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(config));
      } catch {
        /* storage unavailable: fine */
      }
      return config;
    },
    initialData: cached,
    initialDataUpdatedAt: 0, // treat cached data as stale so the live config is always fetched
    staleTime: Infinity,
    // Render's free plan puts the server to sleep when idle; waking up takes up to about a minute.
    // Keep trying for roughly that long instead of showing an error straight away.
    retry: 12,
    retryDelay: 5000,
  });
}
