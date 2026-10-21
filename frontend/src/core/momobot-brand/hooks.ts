import { useQuery } from "@tanstack/react-query";

import { isStaticWebsiteOnly } from "../static-mode";

import {
  BRAND_ABOUT_QUERY_KEY,
  BRAND_KIT_QUERY_KEY,
  fetchBrandAbout,
  fetchBrandKit,
} from "./api";

const options = { retry: false, staleTime: 5 * 60_000 } as const;

/** 404 when the server has no content dir, so `data` stays undefined and nav hides. */
export function useBrandKit() {
  return useQuery({
    queryKey: BRAND_KIT_QUERY_KEY,
    queryFn: fetchBrandKit,
    enabled: !isStaticWebsiteOnly(),
    ...options,
  });
}

export function useBrandAbout() {
  return useQuery({
    queryKey: BRAND_ABOUT_QUERY_KEY,
    queryFn: fetchBrandAbout,
    enabled: !isStaticWebsiteOnly(),
    ...options,
  });
}
