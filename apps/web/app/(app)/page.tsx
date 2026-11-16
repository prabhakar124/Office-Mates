import { Suspense } from "react";

import { SystemStatus, SystemStatusSkeleton } from "@/components/system-status";

export default function OverviewPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
        <p className="text-muted-foreground text-sm">
          Office-Mates is in Phase 0 (foundations). The workspace features in the sidebar are
          enabled as each phase is completed.
        </p>
      </div>

      <Suspense fallback={<SystemStatusSkeleton />}>
        <SystemStatus />
      </Suspense>
    </div>
  );
}
