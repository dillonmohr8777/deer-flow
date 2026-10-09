"use client";

import {
  QueryClient,
  QueryClientProvider as TanStackQueryClientProvider,
} from "@tanstack/react-query";

// One client per browser tab. Exported so logout can drop every cached
// response: a soft navigation keeps this module alive, and the next person
// to sign in on the same tab must not see the previous user's data.
export const queryClient = new QueryClient();

export function QueryClientProvider({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <TanStackQueryClientProvider client={queryClient}>
      {children}
    </TanStackQueryClientProvider>
  );
}
