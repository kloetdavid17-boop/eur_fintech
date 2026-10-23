import { useQuery } from "@tanstack/react-query";
import { getConfig } from "../api";

/** Public app config (plans, limits, which services are configured). Loaded once. */
export function useConfig() {
  return useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
    staleTime: Infinity,
    retry: 1,
  });
}
