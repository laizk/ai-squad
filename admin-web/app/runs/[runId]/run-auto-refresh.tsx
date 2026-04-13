"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export function RunAutoRefresh({ enabled }: { enabled: boolean }) {
  const router = useRouter();

  useEffect(() => {
    if (!enabled) return;

    const intervalId = window.setInterval(() => {
      router.refresh();
    }, 5000);

    return () => window.clearInterval(intervalId);
  }, [enabled, router]);

  if (!enabled) return null;

  return (
    <p className="meta">
      Auto-refreshing every 5 seconds while this run is active.
    </p>
  );
}
