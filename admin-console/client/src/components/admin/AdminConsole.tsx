import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { trpc } from "@/lib/trpc";
import { useAuth } from "@/_core/hooks/useAuth";
import { Activity, AlertTriangle, Bot, Database, FileSearch, Gamepad2, Gauge, KeyRound, Network, RefreshCw, ShieldCheck, Settings2, SlidersHorizontal, Users, Wrench } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { SectionHeading } from "./SectionHeading";
import { StatusBadge, type Availability } from "./StatusBadge";

const componentIcons = { BOT: Bot, TELEGRAM: Network, POSTGRES: Database, REDIS: Activity, CELERY: Gauge, DOCKER: Wrench, SETTINGS: Settings2, GATEWAY: KeyRound };
const knownSettings = ["moderation_level", "anti_raid", "captcha", "antiforward", "lang_policy", "warn_limit", "max_links", "max_mentions", "silent_mode", "smart_responses", "welcome_enabled", "leave_enabled", "welcome_msg", "leave_msg", "rules_text", "modlog_channel"];

function formatDate(value?: string | Date | null) {
  if (!value) return "غير مسجل";
  return new Intl.DateTimeFormat("ar", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function ErrorBox({ text }: { text: string }) {
  return <Alert variant="destructive"><AlertTriangle className="h-4 w-4" /><AlertTitle>لا يمكن إكمال القراءة</AlertTitle><AlertDescription>{text}</AlertDescription></Alert>;
}

export default function AdminConsole() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState("operations");
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [settingsDraft, setSettingsDraft] = useState<Record<string, string>>({});
  const [connectionRegistered, setConnectionRegistered] = useState(false);
  const utils = trpc.useUtils();
  const overview = trpc.admin.overview.useQuery(undefined, { refetchInterval: 60_000 });
  const groups = trpc.admin.groups.list.useQuery(undefined, { enabled: activeTab === "groups" || activeTab === "moderation" });
  const settings = trpc.admin.groups.settings.useQuery({ groupId: selectedGroupId ?? 0 }, { enabled: Boolean(selectedGroupId) && activeTab === "groups" });
  const audit = trpc.admin.audit.list.useQuery({ limit: 50 }, { enabled: activeTab === "audit" });
  const alerts = trpc.admin.alerts.list.useQuery({ limit: 30 }, { enabled: activeTab === "operations" || activeTab === "audit" });
  const probe = trpc.admin.probe.useMutation({
    onSuccess: async result => {
      await utils.admin.overview.invalidate();
      if (result.ok) toast.success("اكتمل الفحص واستُخدمت نتيجة البوابة الفعلية.");
      else toast.error(result.error?.message ?? "تعذر الوصول إلى بوابة البوت.");
    },
    onError: error => toast.error(error.message),
  });
  const registerConnection = trpc.admin.configureConnection.useMutation({
    onSuccess: async () => {
      setConnectionRegistered(true);
      await utils.admin.overview.invalidate();
      toast.success("سُجل اتصال البوابة من الأسرار الخادمية المهيأة.");
    },
    onError: error => toast.error(error.message),
  });
  const updateSettings = trpc.admin.groups.updateSettings.useMutation({
    onSuccess: async result => {
      if (!result.ok) return toast.error(result.error?.message ?? "لم تؤكد البوابة حفظ الإعداد.");
      setSettingsDraft({});
      await utils.admin.groups.settings.invalidate();
      await utils.admin.overview.invalidate();
      toast.success("أكدت بوابة البوت التحديث وسُجل الإجراء للتدقيق.");
    },
    onError: error => toast.error(error.message),
  });
  const acknowledgeAlert = trpc.admin.alerts.acknowledge.useMutation({ onSuccess: () => utils.admin.alerts.invalidate() });

  const checks = overview.data?.health ?? [];
  const latestByComponent = useMemo(() => {
    const map = new Map<string, typeof checks[number]>();
    checks.forEach(check => { if (!map.has(check.component)) map.set(check.component, check); });
    return map;
  }, [checks]);
  const groupRows = (groups.data?.ok ? ((groups.data.data as { groups?: Array<{ id: number; title?: string | null; username?: string | null; isActive: boolean; raidLockdown: boolean }> })?.groups ?? []) : []);
  const currentSettings = settings.data?.ok ? ((settings.data.data as { settings?: Record<string, string> })?.settings ?? {}) : {};

  const chooseGroup = (groupId: number) => {
    setSelectedGroupId(groupId);
    setSettingsDraft({});
  };
  const changeSetting = (key: string, value: string) => setSettingsDraft(current => ({ ...current, [key]: value }));

  return (
    <div dir="rtl" className="mx-auto flex w-full max-w-[1560px] flex-col gap-8 pb-10">
      <div className="rounded-2xl border border-slate-200 bg-[radial-gradient(circle_at_100%_0%,rgba(13,148,136,0.11),transparent_31%),linear-gradient(120deg,#ffffff,#f8fbfb)] px-6 py-6 shadow-[0_18px_55px_rgba(15,23,42,0.06)] md:px-8">
        <p className="text-xs font-bold tracking-[0.2em] text-teal-700">GUARDIAN CONTROL PLANE</p>
        <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div><h1 className="text-3xl font-semibold tracking-tight text-slate-950">مركز تشغيل Guardian Bot</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">لوحة إدارة لا تعرض نجاحاً إلا من مصدر حقيقي. تظهر الإمكانات غير الموصولة كغير متاحة ولا تنفذ إجراءات Telegram دون تحقق الخادم من الهوية والصلاحيات والنتيجة.</p></div>
          <Button onClick={() => probe.mutate()} disabled={probe.isPending} className="bg-teal-700 text-white hover:bg-teal-800"><RefreshCw className={`ml-2 h-4 w-4 ${probe.isPending ? "animate-spin" : ""}`} />فحص البوابة الآن</Button>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="h-auto w-full justify-start overflow-x-auto rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
          <TabsTrigger value="operations" className="gap-2 rounded-lg px-4 py-2.5"><Gauge className="h-4 w-4" />التشغيل</TabsTrigger>
          <TabsTrigger value="groups" className="gap-2 rounded-lg px-4 py-2.5"><SlidersHorizontal className="h-4 w-4" />المجموعات والإعدادات</TabsTrigger>
          <TabsTrigger value="moderation" className="gap-2 rounded-lg px-4 py-2.5"><ShieldCheck className="h-4 w-4" />Moderation</TabsTrigger>
          <TabsTrigger value="members" className="gap-2 rounded-lg px-4 py-2.5"><Users className="h-4 w-4" />الأعضاء</TabsTrigger>
          <TabsTrigger value="games" className="gap-2 rounded-lg px-4 py-2.5"><Gamepad2 className="h-4 w-4" />الألعاب والميزات</TabsTrigger>
          <TabsTrigger value="audit" className="gap-2 rounded-lg px-4 py-2.5"><FileSearch className="h-4 w-4" />التدقيق والتوثيق</TabsTrigger>
          {user?.role === "owner" ? <TabsTrigger value="access" className="gap-2 rounded-lg px-4 py-2.5"><KeyRound className="h-4 w-4" />الصلاحيات</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="operations" className="space-y-6">
          <SectionHeading eyebrow="RUNTIME OBSERVABILITY" title="حالة الخدمة كما تحقق منها النظام" detail="هذه البطاقات تعتمد آخر فحص محفوظ. قبل أول فحص لا تُستبدل النتيجة بتخمين أو بيانات تجريبية." />
          {overview.isLoading ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 8 }).map((_, index) => <Skeleton key={index} className="h-36 rounded-xl" />)}</div> : null}
          {overview.error ? <ErrorBox text={overview.error.message} /> : null}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {["BOT", "TELEGRAM", "POSTGRES", "REDIS", "CELERY", "DOCKER", "SETTINGS", "GATEWAY"].map(component => {
              const item = latestByComponent.get(component);
              const Icon = componentIcons[component as keyof typeof componentIcons];
              return <Card key={component} className="border-slate-200 bg-white shadow-[0_8px_28px_rgba(15,23,42,0.04)]"><CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3"><div className="rounded-lg bg-slate-100 p-2.5 text-slate-700"><Icon className="h-5 w-5" /></div>{item ? <StatusBadge status={item.status as Availability} /> : <span className="text-xs font-medium text-slate-400">لم يفحص بعد</span>}</CardHeader><CardContent><CardTitle className="text-base">{component}</CardTitle><CardDescription className="mt-2 min-h-10 text-xs leading-5">{item?.summary ?? "لا توجد نتيجة تشغيلية مسجلة لهذا المكوّن."}</CardDescription><p className="mt-4 text-[11px] font-medium text-slate-400">{item ? formatDate(item.checkedAt) : "—"}</p></CardContent></Card>;
            })}
          </div>
          <div className="grid gap-6 lg:grid-cols-[1.35fr_0.65fr]">
            <Card><CardHeader><CardTitle>اتصال بوابة البوت</CardTitle><CardDescription>يُضبط عنوان البوابة وسرها من الأسرار الخادمية فقط، ولا يظهر السر في المتصفح أو سجل التدقيق.</CardDescription></CardHeader><CardContent className="space-y-4"><div className="rounded-xl bg-slate-50 p-4 text-sm"><p className="font-medium text-slate-900">{overview.data?.gatewayConfigured ? "السر وعنوان البوابة مهيآن على الخادم." : "لم تُهيأ أسرار بوابة Guardian Bot بعد."}</p><p className="mt-1 text-slate-600">{overview.data?.gateway?.baseUrl ?? "لا يوجد عنوان صالح قابل للعرض."}</p></div><Button variant="outline" onClick={() => registerConnection.mutate()} disabled={!overview.data?.gatewayConfigured || registerConnection.isPending || connectionRegistered}>{connectionRegistered ? "سُجل الاتصال في لوحة الإدارة" : "تسجيل الاتصال من الأسرار"}</Button></CardContent></Card>
            <Card><CardHeader><CardTitle>تنبيهات تحتاج انتباهاً</CardTitle><CardDescription>لا يُنشأ التنبيه من UI؛ مصدره فحص backend أو مهمة مجدولة.</CardDescription></CardHeader><CardContent className="space-y-3">{alerts.data?.length ? alerts.data.slice(0, 4).map(alert => <div key={alert.id} className="rounded-lg border border-slate-200 p-3"><div className="flex items-center justify-between gap-3"><p className="text-sm font-medium">{alert.title}</p><span className="text-[11px] font-bold text-rose-700">{alert.severity}</span></div><p className="mt-1 text-xs leading-5 text-slate-600">{alert.summary}</p><Button size="sm" variant="ghost" className="mt-1 h-7 px-1 text-xs" onClick={() => acknowledgeAlert.mutate({ alertId: alert.id })}>تأكيد الاطلاع</Button></div>) : <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">لا توجد تنبيهات مفتوحة مسجلة.</p>}</CardContent></Card>
          </div>
        </TabsContent>

        <TabsContent value="groups" className="space-y-6">
          <SectionHeading eyebrow="CANONICAL GROUP SETTINGS" title="إعدادات المجموعات من مصدرها الوحيد" detail="كل تعديل يمر عبر group_settings canonical في البوت ثم يثبت في سجل التدقيق. لا توجد نسخة إعدادات محلية بديلة داخل الواجهة." />
          {groups.data && !groups.data.ok ? <ErrorBox text={groups.data.error?.message ?? "لا يمكن الاتصال بمصدر المجموعات."} /> : null}
          <div className="grid gap-6 xl:grid-cols-[0.42fr_0.58fr]">
            <Card><CardHeader><CardTitle>المجموعات المتاحة ضمن نطاقك</CardTitle><CardDescription>تظهر المجموعة فقط إذا سمحت grants الخادمية بقراءتها.</CardDescription></CardHeader><CardContent className="space-y-2">{groups.isLoading ? <Skeleton className="h-32" /> : groupRows.length ? groupRows.map(group => <button key={group.id} onClick={() => chooseGroup(group.id)} className={`w-full rounded-xl border p-4 text-right transition ${selectedGroupId === group.id ? "border-teal-600 bg-teal-50" : "border-slate-200 hover:border-slate-300"}`}><div className="flex items-center justify-between gap-3"><span className="font-medium text-slate-900">{group.title || `Group ${group.id}`}</span><span className="text-xs text-slate-500">{group.isActive ? "نشطة" : "غير نشطة"}</span></div><p className="mt-2 text-xs text-slate-500">{group.username ? `@${group.username}` : group.id}</p>{group.raidLockdown ? <p className="mt-2 text-xs font-semibold text-amber-700">وضع raid lockdown مفعّل</p> : null}</button>) : <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">لا توجد مجموعات متاحة للعرض أو لم تُربط البوابة بعد.</p>}</CardContent></Card>
            <Card><CardHeader><CardTitle>محرر canonical</CardTitle><CardDescription>{selectedGroupId ? `المجموعة ${selectedGroupId}. لا يصبح الحفظ ناجحاً إلا بعد تأكيد بوابة البوت.` : "اختر مجموعة لقراءة الإعدادات المتاحة."}</CardDescription></CardHeader><CardContent>{settings.error ? <ErrorBox text={settings.error.message} /> : null}{selectedGroupId && settings.data && !settings.data.ok ? <ErrorBox text={settings.data.error?.message ?? "تعذر تحميل الإعدادات."} /> : null}{selectedGroupId && settings.data?.ok ? <div className="space-y-5"><div className="grid gap-4 md:grid-cols-2">{knownSettings.map(key => { const value = settingsDraft[key] ?? currentSettings[key] ?? ""; const toggle = ["anti_raid", "captcha", "smart_responses", "silent_mode", "welcome_enabled", "leave_enabled"].includes(key); return <div key={key} className="rounded-xl border border-slate-200 p-4"><div className="mb-3 flex items-center justify-between gap-3"><label className="text-sm font-semibold text-slate-800">{key}</label>{toggle ? <Switch checked={value === "on"} onCheckedChange={checked => changeSetting(key, checked ? "on" : "off")} /> : null}</div>{toggle ? <p className="text-xs text-slate-500">{value === "on" ? "مفعّل" : "معطّل"}</p> : key.endsWith("_msg") || key === "rules_text" ? <Textarea value={value} onChange={event => changeSetting(key, event.target.value)} className="min-h-24 text-sm" /> : <Input value={value} onChange={event => changeSetting(key, event.target.value)} className="text-sm" />}</div>; })}</div><div className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-5"><Button onClick={() => updateSettings.mutate({ groupId: selectedGroupId, changes: settingsDraft })} disabled={!Object.keys(settingsDraft).length || updateSettings.isPending}>{updateSettings.isPending ? "جارٍ التحقق والحفظ…" : `حفظ ${Object.keys(settingsDraft).length || ""} تعديل`}</Button><Button variant="ghost" onClick={() => setSettingsDraft({})} disabled={!Object.keys(settingsDraft).length}>إلغاء المعاينة</Button><p className="text-xs text-slate-500">ستتحقق البوابة من operator Telegram ومن صلاحياته قبل الكتابة.</p></div></div> : <p className="rounded-lg bg-slate-50 p-5 text-sm text-slate-500">لا توجد إعدادات معروضة قبل اختيار مجموعة ونجاح القراءة.</p>}</CardContent></Card>
          </div>
        </TabsContent>

        <TabsContent value="moderation" className="space-y-6"><SectionHeading eyebrow="MODERATION CENTER" title="الأحداث، الإشارات، ونتائج التنفيذ" detail="لا تظهر الأحداث إلا من ModerationEvent الدائم عبر البوابة. حدد مجموعة أولاً؛ لا يستعرض النظام بيانات مجموعات خارج نطاقك." />{!selectedGroupId ? <Alert><ShieldCheck className="h-4 w-4" /><AlertTitle>اختر مجموعة من تبويب الإعدادات</AlertTitle><AlertDescription>سيستخدم المركز group scope نفسه لمنع قراءة أحداث غير مصرح بها.</AlertDescription></Alert> : <ModerationEvents groupId={selectedGroupId} />}</TabsContent>

        <TabsContent value="members" className="space-y-6"><SectionHeading eyebrow="MEMBER OPERATIONS" title="إدارة الأعضاء ضمن تفويض Telegram" detail="إجراءات الكتم والحظر والرجوع لا تتاح من هذا القسم قبل نجاح بوابة التحكم والتحقق live من operator ومن صلاحية البوت. لا تُظهر الواجهة زر نجاح اصطناعي." /><CapabilityBoundary title="المسار محروس لكنه غير مفتوح افتراضياً" detail="يُستكمل العرض وإجراءات الأعضاء بعد اختيار مجموعة والتحقق من gateway والـgrants. الإجراءات المتاحة الآن محصورة بعقد backend ولا تُنفذ من الواجهة عند غياب الاتصال." /></TabsContent>
        <TabsContent value="games" className="space-y-6"><SectionHeading eyebrow="OPTIONAL CAPABILITIES" title="الألعاب والميزات ذات الاعتمادات" detail="جلسات Mafia وChameleon والـscoreboards ستعرض من GameSessionManager فقط. Mafia لا تحصل على نقاط ما لم يوجد scoring contract حقيقي، والمدفوعات والصوت والتنزيلات تبقى معطلة عند غياب provider." /><div className="grid gap-4 md:grid-cols-3"><CapabilityBoundary title="Mafia" detail="حالة الجلسة فقط؛ لا نقاط مصطنعة." /><CapabilityBoundary title="Chameleon" detail="جلسات وscoreboard من Redis عند ربط البوابة." /><CapabilityBoundary title="Providers" detail="حالة fail-closed لكل صوت أو دفع أو fulfillment." /></div></TabsContent>
        {user?.role === "owner" ? <TabsContent value="access" className="space-y-6"><SectionHeading eyebrow="IDENTITY & SCOPES" title="ربط مشرفي الويب بنطاقات المجموعات" detail="هذه الإدارة متاحة لمالك النظام فقط. الربط لا يتجاوز تفويض Telegram؛ تتحقق بوابة البوت من status الحقيقي للمشرف عند كل إجراء على المجموعة." /><AccessManagement /></TabsContent> : null}
        <TabsContent value="audit" className="space-y-6"><SectionHeading eyebrow="AUDIT & RUNBOOK" title="سجل لا تتجاوزه الواجهة" detail="يسجل backend كل mutation محروس بنتيجته وrequest ID. لا يعرض metadata الحساسة، وتبقى التصديرات محكومة بالنطاق والصلاحيات." />{audit.error ? <ErrorBox text={audit.error.message} /> : null}<Card><CardHeader><CardTitle>آخر العمليات المدققة</CardTitle><CardDescription>تشمل الطلبات الناجحة والفاشلة والقرارات الصريحة. لا تكتب الواجهة السجل مباشرة.</CardDescription></CardHeader><CardContent className="overflow-x-auto"><table className="w-full min-w-[760px] text-right text-sm"><thead className="border-b border-slate-200 text-xs text-slate-500"><tr><th className="pb-3 font-medium">الوقت</th><th className="pb-3 font-medium">الإجراء</th><th className="pb-3 font-medium">النتيجة</th><th className="pb-3 font-medium">المجموعة</th><th className="pb-3 font-medium">Request ID</th></tr></thead><tbody>{audit.data?.length ? audit.data.map(row => <tr key={row.id} className="border-b border-slate-100"><td className="py-3 text-slate-600">{formatDate(row.createdAt)}</td><td className="py-3 font-medium">{row.action}</td><td className="py-3">{row.outcome}</td><td className="py-3">{row.groupId ?? "—"}</td><td className="py-3 font-mono text-xs text-slate-500">{row.requestId}</td></tr>) : <tr><td colSpan={5} className="py-8 text-center text-slate-500">لا توجد عمليات مدققة مرئية ضمن نطاقك.</td></tr>}</tbody></table></CardContent></Card><div className="grid gap-4 lg:grid-cols-2"><CapabilityBoundary title="حدود Telegram" detail="المشرف المعتمد وصلاحيات bot وavailability وrate limits ووصول updates هي شروط تشغيل، وليست إشعاراً تجميلياً." /><CapabilityBoundary title="Runbook" detail="هيئ بوابة البوت بالسر الخادمي، اختبر status، اربط operator grants، ثم نفذ mutation staging مدقق قبل الإنتاج." /></div></TabsContent>
      </Tabs>
    </div>
  );
}

function ModerationEvents({ groupId }: { groupId: number }) {
  const events = trpc.admin.moderation.listEvents.useQuery({ groupId, limit: 50 });
  if (events.isLoading) return <Skeleton className="h-72 rounded-xl" />;
  if (events.error) return <ErrorBox text={events.error.message} />;
  if (!events.data?.ok) return <ErrorBox text={events.data?.error?.message ?? "لم تؤكد البوابة القراءة."} />;
  const rows = ((events.data.data as { events?: Array<{ id: number; violationCategory: string; actionTaken: string; riskScore: number; explanation?: string | null; createdAt?: string }> })?.events ?? []);
  return <Card><CardHeader><CardTitle>أحداث المجموعة {groupId}</CardTitle><CardDescription>يُعرض النص التفصيلي في البوابة وفق سياسة redaction؛ لا تُخزن الأسرار في لوحة الإدارة.</CardDescription></CardHeader><CardContent className="space-y-3">{rows.length ? rows.map(event => <div key={event.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-medium text-slate-900">{event.violationCategory} <span className="text-slate-400">→</span> {event.actionTaken}</p><p className="mt-1 text-xs text-slate-500">{formatDate(event.createdAt)}</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">Risk {event.riskScore.toFixed(1)}</span></div>{event.explanation ? <p className="mt-3 text-sm leading-6 text-slate-600">{event.explanation}</p> : null}</div>) : <p className="rounded-lg bg-slate-50 p-5 text-sm text-slate-500">لا توجد أحداث مطابقة في المصدر الحالي.</p>}</CardContent></Card>;
}

function CapabilityBoundary({ title, detail }: { title: string; detail: string }) {
  return <Card className="border-dashed border-slate-300 bg-slate-50/60"><CardHeader><CardTitle className="text-base">{title}</CardTitle><CardDescription className="leading-6">{detail}</CardDescription></CardHeader><CardContent><StatusBadge status="DISABLED" /></CardContent></Card>;
}

function AccessManagement() {
  const operators = trpc.admin.access.operators.useQuery();
  const utils = trpc.useUtils();
  const [userId, setUserId] = useState("");
  const [telegramUserId, setTelegramUserId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [scope, setScope] = useState<"VIEW" | "AUDIT" | "MODERATE" | "CONFIGURE" | "OPERATE" | "OWNER">("VIEW");
  const bind = trpc.admin.access.bindOperator.useMutation({ onSuccess: () => { utils.admin.access.operators.invalidate(); toast.success("تم ربط هوية المشرف وسُجل الإجراء."); } });
  const grant = trpc.admin.access.grantGroup.useMutation({ onSuccess: () => toast.success("تم حفظ نطاق المجموعة وسُجل الإجراء.") });
  const selected = operators.data?.find(row => String(row.user.id) === userId);
  return <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]"><Card><CardHeader><CardTitle>حسابات الويب</CardTitle><CardDescription>تظهر الحسابات التي دخلت إلى اللوحة. لا يصبح الحساب مشغلاً إلا بعد ربط owner لهوية Telegram.</CardDescription></CardHeader><CardContent className="space-y-3">{operators.isLoading ? <Skeleton className="h-44" /> : operators.data?.length ? operators.data.map(row => <button key={row.user.id} onClick={() => setUserId(String(row.user.id))} className={`w-full rounded-xl border p-4 text-right ${userId === String(row.user.id) ? "border-teal-600 bg-teal-50" : "border-slate-200"}`}><div className="flex items-center justify-between gap-3"><span className="font-medium">{row.user.name || row.user.email || row.user.openId}</span><span className="text-xs text-slate-500">{row.user.role}</span></div><p className="mt-2 text-xs text-slate-500">Telegram: {row.profile?.telegramUserId ?? "غير مربوط"} · {row.profile?.isTelegramVerified ? "موثق" : "غير موثق"}</p></button>) : <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">لم يدخل أي حساب ويب بعد.</p>}</CardContent></Card><div className="space-y-6"><Card><CardHeader><CardTitle>ربط هوية Telegram</CardTitle><CardDescription>ينفذ الربط من owner، وتظل صلاحية المجموعة محكومة بتحقق live في بوابة البوت.</CardDescription></CardHeader><CardContent className="space-y-3"><Input inputMode="numeric" value={telegramUserId} onChange={event => setTelegramUserId(event.target.value)} placeholder="Telegram User ID" disabled={!selected} /><Button className="w-full" disabled={!selected || !/^\d+$/.test(telegramUserId) || bind.isPending} onClick={() => bind.mutate({ userId: Number(userId), telegramUserId: Number(telegramUserId) })}>ربط الحساب المحدد</Button></CardContent></Card><Card><CardHeader><CardTitle>منح نطاق مجموعة</CardTitle><CardDescription>لا يكفي grant وحده لتنفيذ Telegram action؛ يلزم أيضاً allowlist وadmin status وصلاحيات bot الفعلية.</CardDescription></CardHeader><CardContent className="space-y-3"><Input inputMode="numeric" value={groupId} onChange={event => setGroupId(event.target.value)} placeholder="Group ID" disabled={!selected} /><select value={scope} onChange={event => setScope(event.target.value as typeof scope)} className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" disabled={!selected}><option value="VIEW">VIEW</option><option value="AUDIT">AUDIT</option><option value="MODERATE">MODERATE</option><option value="CONFIGURE">CONFIGURE</option><option value="OPERATE">OPERATE</option><option value="OWNER">OWNER</option></select><Button className="w-full" variant="outline" disabled={!selected || !/^-?\d+$/.test(groupId) || grant.isPending} onClick={() => grant.mutate({ userId: Number(userId), groupId: Number(groupId), scope })}>منح النطاق</Button></CardContent></Card></div></div>;
}
