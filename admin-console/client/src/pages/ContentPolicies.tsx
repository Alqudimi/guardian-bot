import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import DashboardLayout from "@/components/DashboardLayout";
import { trpc } from "@/lib/trpc";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const ErrorBox = ({ text }: { text: string }) => <Alert variant="destructive"><AlertTriangle className="h-4 w-4" /><AlertTitle>فشلت العملية</AlertTitle><AlertDescription>{text}</AlertDescription></Alert>;

export default function ContentPolicies() {
  const utils = trpc.useUtils();
  const [groupText, setGroupText] = useState("");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [pattern, setPattern] = useState("");
  const [type, setType] = useState<"regex" | "literal">("literal");
  const [category, setCategory] = useState<"spam" | "scam" | "adult" | "phishing" | "abuse" | "other">("spam");
  const patterns = trpc.admin.groups.patterns.useQuery({ groupId: groupId ?? 0 }, { enabled: groupId !== null });
  const report = trpc.admin.groups.report.useQuery({ groupId: groupId ?? 0, days: 7 }, { enabled: groupId !== null });
  const add = trpc.admin.groups.addPattern.useMutation({ onSuccess: async result => { if (!result.ok) return toast.error(result.error?.message ?? "لم تحفظ القاعدة."); setPattern(""); await utils.admin.groups.patterns.invalidate(); toast.success("أكدت البوابة إضافة القاعدة."); } });
  const remove = trpc.admin.groups.removePattern.useMutation({ onSuccess: async result => { if (!result.ok) return toast.error(result.error?.message ?? "لم تحذف القاعدة."); await utils.admin.groups.patterns.invalidate(); } });
  const items = patterns.data?.ok ? ((patterns.data.data as { patterns?: Array<{ id: string; type: string; category: string; pattern: string }> })?.patterns ?? []) : [];
  const reportData = report.data?.ok ? ((report.data.data as { report?: Record<string, unknown> })?.report ?? null) : null;
  const selectGroup = () => {
    if (!/^-?\d+$/.test(groupText)) return toast.error("أدخل Group ID صحيحاً.");
    setGroupId(Number(groupText));
  };
  return <DashboardLayout><main dir="rtl" className="mx-auto w-full max-w-7xl space-y-6 pb-10"><section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><p className="text-xs font-bold tracking-[0.16em] text-teal-700">CONTENT CONTROL</p><h1 className="mt-2 text-3xl font-semibold text-slate-950">قواعد المحتوى والتقارير</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">لا تُدار القواعد من نسخة محلية؛ تتصل اللوحة بالـgroup patterns manager في Guardian Bot. لا ينجح الحفظ قبل validation وتحقق صلاحية المشرف في المجموعة.</p><div className="mt-5 flex max-w-xl gap-3"><Input aria-label="معرف مجموعة Telegram" value={groupText} inputMode="numeric" onChange={event => setGroupText(event.target.value)} placeholder="Group ID" /><Button onClick={selectGroup}>فتح المجموعة</Button></div></section>{groupId === null ? <Alert><ShieldCheck className="h-4 w-4" /><AlertTitle>ابدأ بتحديد المجموعة</AlertTitle><AlertDescription>تتطلب القراءة والكتابة نطاق group مصرحاً وهوية Telegram موثقة.</AlertDescription></Alert> : <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]"><Card><CardHeader><CardTitle>Group patterns</CardTitle><CardDescription>حد أقصى 100 قاعدة و512 حرفاً؛ تعيد البوابة خطأ validation بدلاً من قبول regex غير صالح.</CardDescription></CardHeader><CardContent className="space-y-4"><div className="grid gap-3 md:grid-cols-[1fr_150px_150px]"><Input aria-label="نمط القاعدة" value={pattern} onChange={event => setPattern(event.target.value)} maxLength={512} placeholder="نمط حرفي أو Regex" /><select aria-label="نوع القاعدة" value={type} onChange={event => setType(event.target.value as typeof type)} className="h-10 rounded-md border border-input bg-background px-3 text-sm"><option value="literal">literal</option><option value="regex">regex</option></select><select aria-label="تصنيف القاعدة" value={category} onChange={event => setCategory(event.target.value as typeof category)} className="h-10 rounded-md border border-input bg-background px-3 text-sm"><option value="spam">spam</option><option value="scam">scam</option><option value="adult">adult</option><option value="phishing">phishing</option><option value="abuse">abuse</option><option value="other">other</option></select></div><Button onClick={() => add.mutate({ groupId, type, category, pattern })} disabled={!pattern.trim() || add.isPending}>إضافة قاعدة مدققة</Button>{patterns.isLoading ? <Skeleton className="h-36" /> : patterns.error ? <ErrorBox text={patterns.error.message} /> : patterns.data && !patterns.data.ok ? <ErrorBox text={patterns.data.error?.message ?? "تعذر قراءة القواعد."} /> : <div className="space-y-2">{items.length ? items.map(item => <div key={item.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 p-3"><div className="min-w-0"><p className="break-all font-mono text-sm">{item.pattern}</p><p className="mt-1 text-xs text-slate-500">{item.type} · {item.category} · {item.id}</p></div><Button size="sm" variant="ghost" onClick={() => remove.mutate({ groupId, patternId: item.id })}>حذف</Button></div>) : <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">لا توجد قواعد معروضة من المصدر الحالي.</p>}</div>}</CardContent></Card><Card><CardHeader><CardTitle>تقرير moderation — 7 أيام</CardTitle><CardDescription>قراءة فقط من counters الفعلية في البوت.</CardDescription></CardHeader><CardContent>{report.isLoading ? <Skeleton className="h-48" /> : report.error ? <ErrorBox text={report.error.message} /> : report.data && !report.data.ok ? <ErrorBox text={report.data.error?.message ?? "تعذر توليد التقرير."} /> : reportData ? <pre dir="ltr" className="max-h-[540px] overflow-auto rounded-xl bg-slate-950 p-4 text-left text-xs leading-6 text-slate-100">{JSON.stringify(reportData, null, 2)}</pre> : <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">لا توجد نتيجة تقرير متاحة.</p>}</CardContent></Card></div>}</main></DashboardLayout>;
}
