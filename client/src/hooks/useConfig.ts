import { useQuery } from "@tanstack/react-query";
import { getConfig } from "../api";

/** Public app config (plans, limits, which services are configured). Loaded once. */
export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: Infinity,
    // Render's free plan puts the server to sleep when idle; waking up takes up to about a minute.
    // Keep trying for roughly that long instead of showing an error straight away.
    retry: 12,
    retryDelay: 5000,
  });
}
