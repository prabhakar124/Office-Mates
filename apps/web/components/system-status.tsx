import { connection } from "next/server";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, type Schemas } from "@/lib/api/client";
import { serverGet } from "@/lib/api/server";

type Version = Schemas["VersionResponse"];
type Readiness = Schemas["ReadinessResponse"];

/** Live backend status, fetched on every request (server component, never cached). */
export async function SystemStatus() {
  await connection();

  const [version, readiness] = await Promise.allSettled([
    serverGet<Version>("/version"),
    serverGet<Readiness>("/readyz", { acceptStatuses: [503] }),
  ]);

  if (version.status === "rejected") {
    const err = version.reason;
    // Server-side only; helps diagnose why the API is unreachable.
    console.error("[system-status] /version failed:", err, err instanceof Error ? err.cause : "");
    const reason =
      err instanceof ApiError && err.unreachable
        ? "The API server could not be reached."
        : "The API server returned an error.";
    return (
      <StatusCard badge={<Badge variant="destructive">Unavailable</Badge>} description={reason}>
        <p className="text-muted-foreground text-sm">
          Start it with <code className="font-mono">uv run uvicorn officemates.main:app</code> in{" "}
          <code className="font-mono">apps/backend</code>.
        </p>
      </StatusCard>
    );
  }

  const v = version.value;
  const ready = readiness.status === "fulfilled" ? readiness.value : null;
  const healthy = ready?.status === "ok";

  return (
    <StatusCard
      badge={
        <Badge variant={healthy ? "default" : "destructive"}>
          {healthy ? "Operational" : "Degraded"}
        </Badge>
      }
      description={`${v.name} API v${v.version} · ${v.environment} · ${v.git_sha}`}
    >
      {ready === null ? (
        <p className="text-muted-foreground text-sm">Readiness could not be determined.</p>
      ) : ready.checks.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No dependency checks registered yet. MySQL, Redis and Pinecone checks are added as those
          services arrive in later phases.
        </p>
      ) : (
        <ul className="divide-y text-sm">
          {ready.checks.map((check) => (
            <li key={check.name} className="flex items-center justify-between py-2">
              <span className="font-medium">{check.name}</span>
              <span className="text-muted-foreground flex items-center gap-2">
                {check.duration_ms} ms
                <Badge variant={check.status === "ok" ? "secondary" : "destructive"}>
                  {check.status === "ok" ? "ok" : (check.error ?? "fail")}
                </Badge>
              </span>
            </li>
          ))}
        </ul>
      )}
    </StatusCard>
  );
}

export function SystemStatusSkeleton() {
  return (
    <StatusCard badge={<Skeleton className="h-5 w-20" />} description="Checking the API…">
      <Skeleton className="h-4 w-2/3" />
    </StatusCard>
  );
}

function StatusCard({
  badge,
  description,
  children,
}: {
  badge: React.ReactNode;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-4">
          <CardTitle>System status</CardTitle>
          {badge}
        </div>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
