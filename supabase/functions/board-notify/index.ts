// Project Board overdue digest: one phone push per Melbourne day to admin subscribers
// while any not-done task is past its due date. Called by pg_cron through public.run_board_notify().
import webpush from 'npm:web-push@3.6.7';
import { createClient } from 'npm:@supabase/supabase-js@2.57.4';

const svc = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
const SUPABASE_URL = Deno.env.get('SUPABASE_URL')!;
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


// ---------- staged task reminders: 12h, 6h, 30m before the due time, and when overdue ----------
const STAGES = {
  '12h': { emoji: '🟢', label: 'Due in 12 hours', image: 'icons/board-reminder-12h.png' },
  '6h': { emoji: '🟡', label: 'Due in 6 hours', image: 'icons/board-reminder-6h.png' },
  '30m': { emoji: '🟠', label: 'Due in 30 minutes', image: 'icons/board-reminder-30m.png' },
  'overdue': { emoji: '🔴', label: 'OVERDUE', image: 'icons/board-reminder-overdue.png' }
} as const;
type Stage = keyof typeof STAGES;
const ORDER: Stage[] = ['12h', '6h', '30m', 'overdue'];
const HOUR = 3600_000;

function stageFor(dueMs: number, nowMs: number): Stage | null {
  const left = dueMs - nowMs;
  if (left <= 0) return 'overdue';
  if (left <= 0.5 * HOUR) return '30m';
  if (left <= 6 * HOUR) return '6h';
  if (left <= 12 * HOUR) return '12h';
  return null;
}
const dueText = (iso: string) => new Intl.DateTimeFormat('en-AU', {
  timeZone: 'Australia/Melbourne', weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit'
}).format(new Date(iso));

async function sign(secret: string, taskId: string) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(taskId + ':mute'));
  return Array.from(new Uint8Array(mac)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function reminders(secret: string, dry: boolean) {
  const nowMs = Date.now();
  const horizon = new Date(nowMs + 12 * HOUR).toISOString();
  const floor = new Date(nowMs - 2 * HOUR).toISOString(); // never alert about something more than 2h late
  const { data: tasks, error } = await svc.from('board_tasks')
    .select('id,title,due_at').neq('col', 'done').eq('mute_reminders', false)
    .not('due_at', 'is', null).lte('due_at', horizon).gte('due_at', floor);
  if (error) throw new Error('reminder tasks: ' + error.message);
  if (!tasks?.length) return { ok: true, due: 0 };

  const ids = tasks.map((t) => t.id);
  const { data: logged } = await svc.from('board_reminder_log').select('task_id,stage,due_at').in('task_id', ids);
  const seen = new Set((logged || []).map((l) => `${l.task_id}|${l.stage}|${new Date(l.due_at).getTime()}`));

  const todo: { t: typeof tasks[number]; stage: Stage }[] = [];
  for (const t of tasks) {
    const dueMs = new Date(t.due_at).getTime();
    const stage = stageFor(dueMs, nowMs);
    if (stage && !seen.has(`${t.id}|${stage}|${dueMs}`)) todo.push({ t, stage });
  }
  if (!todo.length) return { ok: true, due: tasks.length, pending: 0 };

  const { data: subs, error: se } = await svc.from('push_subscriptions')
    .select('id,endpoint,p256dh,auth_key,origin,profiles!inner(is_admin,disabled)')
    .eq('enabled', true).eq('profiles.is_admin', true).eq('profiles.disabled', false);
  if (se) throw new Error('subs: ' + se.message);
  if (dry) return { ok: true, dry: true, pending: todo.map((x) => ({ title: x.t.title, stage: x.stage })), admin_subscribers: (subs || []).length };
  if (!subs?.length) return { ok: true, skipped: 'no-admin-subscribers', pending: todo.length };

  const { data: cfg, error: ce } = await svc.from('push_config').select('public_key,private_key').eq('id', 1).single();
  if (ce || !cfg) throw new Error('push is not configured');
  webpush.setVapidDetails('mailto:notifications@indifeels.com', cfg.public_key, cfg.private_key);

  let sent = 0;
  for (const { t, stage } of todo) {
    const st = STAGES[stage];
    const sig = await sign(secret, t.id);
    let delivered = 0;
    for (const s of subs) {
      const base = String(s.origin || '').replace(/\/$/, '');
      const payload = {
        title: `${st.emoji} Task reminder`,
        body: `${clip(t.title, 80)}\n${st.label} · ${dueText(t.due_at)}`,
        url: `${base}/?board_task=${t.id}#project-board`,
        tag: 'indifeels-task-' + t.id,
        image: `${base}/${st.image}`,
        stage,
        muteUrl: `${SUPABASE_URL}/functions/v1/board-notify?action=mute&task=${t.id}&sig=${sig}`,
        requireInteraction: stage === 'overdue' || stage === '30m'
      };
      try {
        await webpush.sendNotification(
          { endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth_key } },
          JSON.stringify(payload),
          { TTL: 60 * 60, urgency: stage === 'overdue' || stage === '30m' ? 'high' : 'normal' }
        );
        delivered++;
      } catch (e) {
        const status = Number((e as { statusCode?: number })?.statusCode || 0);
        if (status === 404 || status === 410) {
          await svc.from('push_subscriptions').update({ enabled: false, updated_at: new Date().toISOString() }).eq('id', s.id);
        }
      }
    }
    if (delivered > 0) {
      sent += delivered;
      // log this stage and every earlier one, so a late-created task doesn't replay old stages
      const rows = ORDER.slice(0, ORDER.indexOf(stage) + 1).map((g) => ({ task_id: t.id, stage: g, due_at: t.due_at }));
      await svc.from('board_reminder_log').upsert(rows, { onConflict: 'task_id,stage,due_at', ignoreDuplicates: true });
    }
  }
  return { ok: true, sent, pending: todo.length };
}

// ---------- "card moved" push: sent by a database trigger whenever a task changes column ----------
const COL_NAMES: Record<string, string> = { backlog: 'To Do', todo: 'Planned', progress: 'In Progress', stuck: 'Roadblocks', done: 'Done' };
const COL_EMOJI: Record<string, string> = { backlog: '📝', todo: '📅', progress: '🚧', stuck: '⛔', done: '✅' };

async function moved(taskId: string, from: string, to: string) {
  const isNew = from === 'new';   // a task that was just added
  if (!COL_NAMES[to] || (!isNew && (!COL_NAMES[from] || from === to))) return { ok: true, skipped: 'bad-columns' };
  const { data: t, error } = await svc.from('board_tasks').select('id,title').eq('id', taskId).maybeSingle();
  if (error) throw new Error('task: ' + error.message);
  if (!t) return { ok: true, skipped: 'task-gone' };
  const { data: subs, error: se } = await svc.from('push_subscriptions')
    .select('id,endpoint,p256dh,auth_key,origin,profiles!inner(is_admin,disabled)')
    .eq('enabled', true).eq('profiles.is_admin', true).eq('profiles.disabled', false);
  if (se) throw new Error('subs: ' + se.message);
  if (!subs?.length) return { ok: true, skipped: 'no-admin-subscribers' };
  const { data: cfg, error: ce } = await svc.from('push_config').select('public_key,private_key').eq('id', 1).single();
  if (ce || !cfg) throw new Error('push is not configured');
  webpush.setVapidDetails('mailto:notifications@indifeels.com', cfg.public_key, cfg.private_key);
  let sent = 0;
  for (const s of subs) {
    const base = String(s.origin || '').replace(/\/$/, '');
    const payload = {
      title: isNew ? `🆕 New task added · ${COL_NAMES[to]}` : `${COL_EMOJI[to]} Task moved to ${COL_NAMES[to]}`,
      body: isNew ? clip(t.title, 120) : `${clip(t.title, 90)}\n${COL_NAMES[from]} → ${COL_NAMES[to]}`,
      url: `${base}/?board_task=${t.id}#project-board`,
      tag: (isNew ? 'indifeels-new-' : 'indifeels-move-') + t.id
    };
    try {
      await webpush.sendNotification({ endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth_key } }, JSON.stringify(payload), { TTL: 60 * 60, urgency: 'normal' });
      sent++;
    } catch (e) {
      const status = Number((e as { statusCode?: number })?.statusCode || 0);
      if (status === 404 || status === 410) await svc.from('push_subscriptions').update({ enabled: false, updated_at: new Date().toISOString() }).eq('id', s.id);
    }
  }
  return { ok: true, sent };
}

async function check(dry: boolean) {
  const now = melbourneNow();
  if (!dry) {
    if (now.minutes < SEND_FROM_MIN || now.minutes >= SEND_UNTIL_MIN) return { ok: true, skipped: 'outside-window' };
    const { data: st } = await svc.from('board_notify_state').select('last_digest_on').eq('id', 1).maybeSingle();
    if (st?.last_digest_on === now.date) return { ok: true, skipped: 'already-sent' };
  }

  const { data: tasks, error } = await svc.from('board_tasks')
    .select('id,title,due_date').neq('col', 'done').eq('mute_reminders', false).not('due_date', 'is', null).lte('due_date', now.date).order('due_date');
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
  const action = u.searchParams.get('action');
  if (req.method !== 'POST' || (action !== 'check' && action !== 'mute' && action !== 'moved')) return reply({ error: 'Not found' }, 404);
  const { data: secret, error } = await svc.rpc('report_scheduler_secret');
  if (error || !secret) return reply({ error: 'Not authorized' }, 401);

  // "Never remind me about this task" button on the phone notification: signed per task, no login needed.
  if (action === 'mute') {
    const task = u.searchParams.get('task') || '';
    const sig = u.searchParams.get('sig') || '';
    if (!/^[0-9a-f-]{36}$/.test(task) || sig !== await sign(String(secret), task)) return reply({ error: 'Not authorized' }, 401);
    const { error: me } = await svc.from('board_tasks').update({ mute_reminders: true }).eq('id', task);
    return me ? reply({ ok: false, error: me.message }, 500) : reply({ ok: true, muted: task });
  }

  if (req.headers.get('x-schedule-token') !== secret) return reply({ error: 'Not authorized' }, 401);
  if (action === 'moved') {
    try { return reply(await moved(u.searchParams.get('task') || '', u.searchParams.get('from') || '', u.searchParams.get('to') || '')); }
    catch (e) { return reply({ ok: false, error: String((e as Error).message || e) }, 500); }
  }
  const dry = u.searchParams.get('dry') === '1';
  try {
    const rem = await reminders(String(secret), dry).catch((e) => ({ ok: false, error: String((e as Error).message || e) }));
    const digest = await check(dry);
    return reply({ reminders: rem, digest });
  } catch (e) { return reply({ ok: false, error: String((e as Error).message || e) }, 500); }
});
