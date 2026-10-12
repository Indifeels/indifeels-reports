// Project Board overdue digest: one phone push per Melbourne day to admin subscribers
// while any not-done task is past its due date. Called by pg_cron through public.run_board_notify().
import webpush from 'npm:web-push@3.6.7';
import { createClient } from 'npm:@supabase/supabase-js@2.57.4';

const svc = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
const headers = { 'Content-Type': 'application/json' };
const reply = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers });

const SEND_FROM_MIN = 8 * 60 + 30; // 8:30 am Melbourne
const SEND_UNTIL_MIN = 20 * 60;    // stop trying after 8:00 pm

function melbourneNow() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Australia/Melbourne', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).formatToParts(new Date());
  const g = (t: string) => parts.find((p) => p.type === t)!.value;
  return { date: `${g('year')}-${g('month')}-${g('day')}`, minutes: Number(g('hour')) * 60 + Number(g('minute')) };
}
const dayNum = (iso: string) => { const [y, m, d] = iso.split('-').map(Number); return Date.UTC(y, m - 1, d) / 86400000; };
const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s);

async function check(dry: boolean) {
  const now = melbourneNow();
  if (!dry) {
    if (now.minutes < SEND_FROM_MIN || now.minutes >= SEND_UNTIL_MIN) return { ok: true, skipped: 'outside-window' };
    const { data: st } = await svc.from('board_notify_state').select('last_digest_on').eq('id', 1).maybeSingle();
    if (st?.last_digest_on === now.date) return { ok: true, skipped: 'already-sent' };
  }

  const { data: tasks, error } = await svc.from('board_tasks')
    .select('id,title,due_date').neq('col', 'done').not('due_date', 'is', null).lte('due_date', now.date).order('due_date');
  if (error) throw new Error('tasks: ' + error.message);
  const overdue = (tasks || []).filter((t) => t.due_date < now.date);
  const dueToday = (tasks || []).filter((t) => t.due_date === now.date);
  if (!overdue.length) return { ok: true, skipped: 'nothing-overdue', due_today: dueToday.length, ...(dry ? { dry: true } : {}) };

  const title = `${overdue.length} overdue task${overdue.length === 1 ? '' : 's'}` +
    (dueToday.length ? ` · ${dueToday.length} due today` : '');
  const shown = overdue.slice(0, 3).map((t) => {
    const late = dayNum(now.date) - dayNum(t.due_date);
    return `${clip(t.title, 60)} (${late}d late)`;
  });
  const body = shown.join(' · ') + (overdue.length > 3 ? ` · +${overdue.length - 3} more` : '');

  // Admins only: the board is an admin panel.
  const { data: subs, error: se } = await svc.from('push_subscriptions')
    .select('id,endpoint,p256dh,auth_key,origin,profiles!inner(is_admin,disabled)')
    .eq('enabled', true).eq('profiles.is_admin', true).eq('profiles.disabled', false);
  if (se) throw new Error('subs: ' + se.message);

  if (dry) return { ok: true, dry: true, today: now.date, overdue: overdue.length, due_today: dueToday.length, title, body, admin_subscribers: (subs || []).length };
  if (!subs?.length) return { ok: true, skipped: 'no-admin-subscribers', overdue: overdue.length };

  const { data: cfg, error: ce } = await svc.from('push_config').select('public_key,private_key').eq('id', 1).single();
  if (ce || !cfg) throw new Error('push is not configured');
  webpush.setVapidDetails('mailto:notifications@indifeels.com', cfg.public_key, cfg.private_key);

  let sent = 0;
  for (const s of subs) {
    try {
      await webpush.sendNotification(
        { endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth_key } },
        JSON.stringify({ title, body, url: String(s.origin || '').replace(/\/$/, '') + '/#project-board', tag: 'indifeels-board-overdue' }),
        { TTL: 60 * 60 * 12, urgency: 'normal' }
      );
      sent++;
    } catch (e) {
      const status = Number((e as { statusCode?: number })?.statusCode || 0);
      if (status === 404 || status === 410) {
        await svc.from('push_subscriptions').update({ enabled: false, updated_at: new Date().toISOString() }).eq('id', s.id);
      }
    }
  }
  if (sent > 0) await svc.from('board_notify_state').update({ last_digest_on: now.date }).eq('id', 1);
  return { ok: true, sent, overdue: overdue.length };
}

Deno.serve(async (req: Request) => {
  const u = new URL(req.url);
  if (req.method !== 'POST' || u.searchParams.get('action') !== 'check') return reply({ error: 'Not found' }, 404);
  const { data: secret, error } = await svc.rpc('report_scheduler_secret');
  if (error || !secret || req.headers.get('x-schedule-token') !== secret) return reply({ error: 'Not authorized' }, 401);
  try { return reply(await check(u.searchParams.get('dry') === '1')); }
  catch (e) { return reply({ ok: false, error: String((e as Error).message || e) }, 500); }
});
