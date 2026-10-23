import { useQuery } from "@tanstack/react-query";
import { getUsage } from "../api";

/** Monthly allowance, straight from the server (never counted on the client). */
export function useUsage(enabled = true) {
  return useQuery({ queryKey: ["usage"], queryFn: getUsage, enabled, staleTime: 5_000 });
}
