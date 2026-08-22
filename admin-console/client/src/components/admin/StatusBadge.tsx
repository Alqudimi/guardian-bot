import { Badge } from "@/components/ui/badge";

export type Availability = "AVAILABLE" | "DEGRADED" | "UNAVAILABLE" | "DISABLED";

const labels: Record<Availability, string> = {
  AVAILABLE: "متاح ومتحقق",
  DEGRADED: "متدهور",
  UNAVAILABLE: "غير متاح",
  DISABLED: "معطل",
};

const styles: Record<Availability, string> = {
  AVAILABLE: "border-emerald-200 bg-emerald-50 text-emerald-800",
  DEGRADED: "border-amber-200 bg-amber-50 text-amber-800",
  UNAVAILABLE: "border-rose-200 bg-rose-50 text-rose-800",
  DISABLED: "border-slate-200 bg-slate-100 text-slate-700",
};

export function StatusBadge({ status }: { status: Availability }) {
  return <Badge variant="outline" className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${styles[status]}`}>{labels[status]}</Badge>;
}
