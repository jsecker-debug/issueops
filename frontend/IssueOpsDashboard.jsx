import React, { useState, useMemo } from 'react';

// ---------------------------------------------------------------------------
// Demo data — 8 realistic issues spanning every status
// ---------------------------------------------------------------------------
const DEMO_ISSUES = [
  {
    id: 1042,
    title: 'Stripe webhook handler drops duplicate events',
    labels: ['bug', 'payments'],
    age: '3d',
    complexity: 'Medium',
    status: 'triaged',
    triageSummary:
      'Duplicate Stripe events (e.g. invoice.paid) are silently dropped because the idempotency check uses only event ID without considering retry headers. Root cause is in packages/payments/src/webhooks.ts — the dedup map is in-memory and resets on deploy. Recommend adding a Redis-based dedup window.',
    devinSessionUrl: 'https://app.devin.ai/sessions/abc123',
    prUrl: null,
  },
  {
    id: 1038,
    title: 'Auth token refresh race condition',
    labels: ['bug', 'auth', 'critical'],
    age: '5d',
    complexity: 'High',
    status: 'fixing',
    triageSummary:
      'When two concurrent requests detect an expired access token, both attempt to refresh it simultaneously. The second refresh invalidates the first new token, causing a logout loop. Needs a mutex/queue around the refresh call in packages/auth/src/tokenManager.ts.',
    devinSessionUrl: 'https://app.devin.ai/sessions/def456',
    prUrl: null,
  },
  {
    id: 1035,
    title: 'Add CSV export to reporting dashboard',
    labels: ['feature', 'reporting'],
    age: '7d',
    complexity: 'Low',
    status: 'pr_opened',
    triageSummary:
      'Feature request to add a "Download CSV" button to the /reports page. Data is already available via the existing REST endpoint — just need a client-side conversion using the Blob API and a download trigger.',
    devinSessionUrl: 'https://app.devin.ai/sessions/ghi789',
    prUrl: 'https://github.com/finserv/monorepo/pull/287',
  },
  {
    id: 1051,
    title: 'Dashboard chart tooltip clipped at viewport edge',
    labels: ['bug', 'ui'],
    age: '1d',
    complexity: 'Low',
    status: 'queued',
    triageSummary: null,
    devinSessionUrl: null,
    prUrl: null,
  },
  {
    id: 1047,
    title: 'Migrate user preferences to new schema',
    labels: ['chore', 'database'],
    age: '4d',
    complexity: 'Medium',
    status: 'triaging',
    triageSummary: null,
    devinSessionUrl: 'https://app.devin.ai/sessions/jkl012',
    prUrl: null,
  },
  {
    id: 1029,
    title: 'Rate limiter blocks legitimate burst traffic from batch API',
    labels: ['bug', 'api', 'infrastructure'],
    age: '9d',
    complexity: 'High',
    status: 'pr_opened',
    triageSummary:
      'The token-bucket rate limiter in packages/api-gateway does not account for authenticated batch endpoints, which legitimately send 50+ requests in rapid succession. Need to add a per-route override config and exempt batch endpoints.',
    devinSessionUrl: 'https://app.devin.ai/sessions/mno345',
    prUrl: 'https://github.com/finserv/monorepo/pull/291',
  },
  {
    id: 1053,
    title: 'Flaky E2E test: checkout flow times out on CI',
    labels: ['bug', 'testing', 'ci'],
    age: '12h',
    complexity: 'Medium',
    status: 'failed',
    triageSummary:
      'Triage failed — unable to reproduce locally. The Playwright test for the checkout flow intermittently times out waiting for the Stripe Elements iframe to load in the CI environment. May be related to network policy or sandbox configuration.',
    devinSessionUrl: 'https://app.devin.ai/sessions/pqr678',
    prUrl: null,
  },
  {
    id: 1044,
    title: 'Implement SSO SAML integration for enterprise clients',
    labels: ['feature', 'auth', 'enterprise'],
    age: '2d',
    complexity: 'High',
    status: 'queued',
    triageSummary: null,
    devinSessionUrl: null,
    prUrl: null,
  },
];

// ---------------------------------------------------------------------------
// Status / color configuration
// ---------------------------------------------------------------------------
const STATUS_CONFIG = {
  queued: { label: 'Queued', color: '#6b7280', bg: '#f3f4f6', darkBg: '#374151', pulse: false },
  triaging: { label: 'Triaging', color: '#8b5cf6', bg: '#ede9fe', darkBg: '#4c1d95', pulse: true },
  triaged: { label: 'Triaged', color: '#0d9488', bg: '#ccfbf1', darkBg: '#134e4a', pulse: false },
  fixing: { label: 'Fixing', color: '#8b5cf6', bg: '#ede9fe', darkBg: '#4c1d95', pulse: true },
  pr_opened: { label: 'PR Opened', color: '#16a34a', bg: '#dcfce7', darkBg: '#14532d', pulse: false },
  failed: { label: 'Failed', color: '#dc2626', bg: '#fee2e2', darkBg: '#7f1d1d', pulse: false },
};

const COMPLEXITY_COLORS = {
  Low: { color: '#16a34a', bg: '#dcfce7', darkBg: '#14532d' },
  Medium: { color: '#d97706', bg: '#fef3c7', darkBg: '#78350f' },
  High: { color: '#dc2626', bg: '#fee2e2', darkBg: '#7f1d1d' },
};

const LABEL_COLORS = {
  bug: '#dc2626',
  feature: '#8b5cf6',
  chore: '#6b7280',
  payments: '#0891b2',
  auth: '#d97706',
  critical: '#dc2626',
  reporting: '#2563eb',
  ui: '#ec4899',
  database: '#0d9488',
  api: '#2563eb',
  infrastructure: '#6366f1',
  testing: '#f59e0b',
  ci: '#6b7280',
  enterprise: '#7c3aed',
};

const FILTER_TABS = [
  { key: 'all', label: 'All' },
  { key: 'queued', label: 'Queued' },
  { key: 'triaging', label: 'Triaging' },
  { key: 'triaged', label: 'Triaged' },
  { key: 'fixing', label: 'Fixing' },
  { key: 'pr_opened', label: 'PRs' },
];

// ---------------------------------------------------------------------------
// Keyframe injection (runs once)
// ---------------------------------------------------------------------------
const STYLE_ID = 'issueops-dashboard-keyframes';
function ensureKeyframes() {
  if (typeof document === 'undefined') return;
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&display=swap');
    @keyframes issueops-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.55; }
    }
    @keyframes issueops-live-dot {
      0%, 100% { transform: scale(1); opacity: 1; }
      50% { transform: scale(1.4); opacity: 0.6; }
    }
  `;
  document.head.appendChild(style);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function useTheme() {
  const [dark, setDark] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  React.useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e) => setDark(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  return dark;
}

function tokens(dark) {
  return {
    bg: dark ? '#0f1117' : '#f8f9fb',
    surface: dark ? '#1a1d27' : '#ffffff',
    surfaceHover: dark ? '#242836' : '#f1f3f8',
    border: dark ? '#2a2e3a' : '#e2e5ed',
    text: dark ? '#e4e6ed' : '#1a1d27',
    textSecondary: dark ? '#9ca0ad' : '#6b7280',
    textMuted: dark ? '#6b7280' : '#9ca3af',
    inputBg: dark ? '#242836' : '#f1f3f8',
    shadow: dark
      ? '0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3)'
      : '0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
    shadowLg: dark
      ? '0 4px 12px rgba(0,0,0,0.5)'
      : '0 4px 12px rgba(0,0,0,0.08)',
  };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function LiveIndicator({ t }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#16a34a', fontWeight: 500 }}>
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: '#16a34a',
          display: 'inline-block',
          animation: 'issueops-live-dot 2s ease-in-out infinite',
        }}
      />
      Live
    </span>
  );
}

function StatCard({ label, value, accentColor, t }) {
  return (
    <div
      style={{
        flex: '1 1 0',
        minWidth: 140,
        background: t.surface,
        borderRadius: 12,
        padding: '20px 22px',
        borderLeft: `4px solid ${accentColor}`,
        boxShadow: t.shadow,
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        transition: 'box-shadow 0.2s',
      }}
    >
      <span style={{ fontSize: 13, color: t.textSecondary, fontWeight: 500, letterSpacing: 0.2 }}>{label}</span>
      <span style={{ fontSize: 32, fontWeight: 700, color: t.text, lineHeight: 1.1 }}>{value}</span>
    </div>
  );
}

function PipelineBar({ issues, t }) {
  const total = issues.length || 1;
  const counts = {};
  issues.forEach((i) => {
    counts[i.status] = (counts[i.status] || 0) + 1;
  });
  const segments = [
    { status: 'queued', color: '#6b7280' },
    { status: 'triaging', color: '#8b5cf6' },
    { status: 'triaged', color: '#0d9488' },
    { status: 'fixing', color: '#8b5cf6' },
    { status: 'pr_opened', color: '#16a34a' },
    { status: 'failed', color: '#dc2626' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div
        style={{
          display: 'flex',
          height: 8,
          borderRadius: 4,
          overflow: 'hidden',
          background: t.border,
        }}
      >
        {segments.map((seg) => {
          const pct = ((counts[seg.status] || 0) / total) * 100;
          if (pct === 0) return null;
          return (
            <div
              key={seg.status}
              title={`${STATUS_CONFIG[seg.status].label}: ${counts[seg.status]}`}
              style={{
                width: `${pct}%`,
                background: seg.color,
                transition: 'width 0.4s ease',
              }}
            />
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {segments.map((seg) => {
          const count = counts[seg.status] || 0;
          if (count === 0) return null;
          return (
            <span key={seg.status} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: t.textSecondary }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: seg.color, display: 'inline-block' }} />
              {STATUS_CONFIG[seg.status].label} ({count})
            </span>
          );
        })}
      </div>
    </div>
  );
}

function StatusBadge({ status, dark }) {
  const cfg = STATUS_CONFIG[status];
  if (!cfg) return null;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 10px',
        borderRadius: 9999,
        fontSize: 12,
        fontWeight: 600,
        color: cfg.color,
        background: dark ? cfg.darkBg : cfg.bg,
        animation: cfg.pulse ? 'issueops-pulse 2s ease-in-out infinite' : 'none',
        whiteSpace: 'nowrap',
      }}
    >
      {cfg.pulse && (
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: cfg.color, display: 'inline-block' }} />
      )}
      {cfg.label}
    </span>
  );
}

function ComplexityBadge({ complexity, dark }) {
  const cfg = COMPLEXITY_COLORS[complexity];
  if (!cfg) return null;
  return (
    <span
      style={{
        padding: '2px 9px',
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 600,
        color: cfg.color,
        background: dark ? cfg.darkBg : cfg.bg,
      }}
    >
      {complexity}
    </span>
  );
}

function LabelBadge({ label, t }) {
  const color = LABEL_COLORS[label] || '#6b7280';
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 7px',
        borderRadius: 9999,
        fontSize: 11,
        fontWeight: 500,
        color: color,
        border: `1px solid ${color}40`,
        background: `${color}12`,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
}

function FilterPill({ label, active, onClick, t }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '6px 16px',
        borderRadius: 9999,
        border: 'none',
        fontSize: 13,
        fontWeight: 600,
        cursor: 'pointer',
        transition: 'all 0.15s',
        background: active ? '#6366f1' : t.inputBg,
        color: active ? '#fff' : t.textSecondary,
        fontFamily: 'inherit',
      }}
    >
      {label}
    </button>
  );
}

function ActionButton({ children, variant, href, onClick, t }) {
  const isPrimary = variant === 'primary';
  const isLink = !!href;

  const baseStyle = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '7px 16px',
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
    border: 'none',
    fontFamily: 'inherit',
    textDecoration: 'none',
    transition: 'all 0.15s',
    background: isPrimary ? '#6366f1' : t.inputBg,
    color: isPrimary ? '#fff' : t.text,
  };

  if (isLink) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" style={baseStyle}>
        {children}
      </a>
    );
  }
  return (
    <button onClick={onClick} style={baseStyle}>
      {children}
    </button>
  );
}

function ExpandedRow({ issue, dark, t, onAction }) {
  return (
    <tr>
      <td colSpan={5} style={{ padding: 0 }}>
        <div
          style={{
            padding: '16px 24px 20px 56px',
            background: dark ? '#14161e' : '#f8f9fb',
            borderBottom: `1px solid ${t.border}`,
          }}
        >
          {issue.triageSummary && (
            <div
              style={{
                background: t.surface,
                border: `1px solid ${t.border}`,
                borderRadius: 10,
                padding: '14px 18px',
                marginBottom: 14,
                fontSize: 13,
                lineHeight: 1.65,
                color: t.textSecondary,
              }}
            >
              <span style={{ fontWeight: 600, color: t.text, display: 'block', marginBottom: 6, fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Triage Summary
              </span>
              {issue.triageSummary}
            </div>
          )}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {issue.devinSessionUrl && (
              <ActionButton href={issue.devinSessionUrl} t={t}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg>
                View Devin Session
              </ActionButton>
            )}
            {issue.prUrl && (
              <ActionButton href={issue.prUrl} t={t}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M6 21V9a9 9 0 0 0 9 9" /></svg>
                View PR
              </ActionButton>
            )}
            {issue.status === 'queued' && (
              <ActionButton variant="primary" onClick={() => onAction(issue.id, 'triaging')} t={t}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" /></svg>
                Triage with Devin
              </ActionButton>
            )}
            {issue.status === 'triaged' && (
              <ActionButton variant="primary" onClick={() => onAction(issue.id, 'fixing')} t={t}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" /></svg>
                Fix with Devin
              </ActionButton>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function IssueOpsDashboard() {
  ensureKeyframes();

  const dark = useTheme();
  const t = tokens(dark);

  const [issues, setIssues] = useState(DEMO_ISSUES);
  const [search, setSearch] = useState('');
  const [activeFilter, setActiveFilter] = useState('all');
  const [expandedId, setExpandedId] = useState(null);

  // Derived data
  const filtered = useMemo(() => {
    let list = issues;
    if (activeFilter !== 'all') {
      list = list.filter((i) => i.status === activeFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (i) =>
          i.title.toLowerCase().includes(q) ||
          String(i.id).includes(q)
      );
    }
    return list;
  }, [issues, activeFilter, search]);

  const stats = useMemo(() => {
    const s = { total: issues.length, pr_opened: 0, inFlight: 0, triaged: 0, failed: 0 };
    issues.forEach((i) => {
      if (i.status === 'pr_opened') s.pr_opened++;
      if (i.status === 'triaging' || i.status === 'fixing') s.inFlight++;
      if (i.status === 'triaged') s.triaged++;
      if (i.status === 'failed') s.failed++;
    });
    return s;
  }, [issues]);

  function handleAction(issueId, newStatus) {
    setIssues((prev) =>
      prev.map((i) =>
        i.id === issueId
          ? {
              ...i,
              status: newStatus,
              devinSessionUrl: i.devinSessionUrl || `https://app.devin.ai/sessions/${Date.now()}`,
            }
          : i
      )
    );
  }

  // ---- Render ----
  return (
    <div
      style={{
        fontFamily: "'DM Sans', system-ui, -apple-system, sans-serif",
        background: t.bg,
        color: t.text,
        minHeight: '100vh',
        padding: '0 0 60px',
        transition: 'background 0.2s, color 0.2s',
      }}
    >
      {/* Header */}
      <header
        style={{
          background: t.surface,
          borderBottom: `1px solid ${t.border}`,
          padding: '18px 32px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: t.shadow,
          position: 'sticky',
          top: 0,
          zIndex: 50,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {/* Logo icon */}
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: -0.3 }}>IssueOps</span>
              <LiveIndicator t={t} />
            </div>
            <span style={{ fontSize: 13, color: t.textSecondary, fontWeight: 400 }}>
              FinServ Co — Monorepo Issue Command Center
            </span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main style={{ maxWidth: 1200, margin: '0 auto', padding: '28px 24px 0' }}>
        {/* Stats Row */}
        <section style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 24 }}>
          <StatCard label="Total Tracked" value={stats.total} accentColor="#6366f1" t={t} />
          <StatCard label="PRs Opened" value={stats.pr_opened} accentColor="#16a34a" t={t} />
          <StatCard label="In Flight" value={stats.inFlight} accentColor="#8b5cf6" t={t} />
          <StatCard label="Ready to Fix" value={stats.triaged} accentColor="#0d9488" t={t} />
          <StatCard label="Failed" value={stats.failed} accentColor="#dc2626" t={t} />
        </section>

        {/* Pipeline Bar */}
        <section
          style={{
            background: t.surface,
            borderRadius: 12,
            padding: '16px 22px',
            marginBottom: 24,
            boxShadow: t.shadow,
          }}
        >
          <span style={{ fontSize: 12, fontWeight: 600, color: t.textSecondary, textTransform: 'uppercase', letterSpacing: 0.5, display: 'block', marginBottom: 10 }}>
            Pipeline
          </span>
          <PipelineBar issues={issues} t={t} />
        </section>

        {/* Filter Bar */}
        <section
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            marginBottom: 20,
            flexWrap: 'wrap',
          }}
        >
          {/* Search */}
          <div style={{ position: 'relative', flex: '0 1 280px', minWidth: 180 }}>
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke={t.textMuted}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              placeholder="Search issues..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                width: '100%',
                padding: '9px 14px 9px 38px',
                borderRadius: 10,
                border: `1px solid ${t.border}`,
                background: t.inputBg,
                color: t.text,
                fontSize: 14,
                fontFamily: 'inherit',
                outline: 'none',
                boxSizing: 'border-box',
                transition: 'border-color 0.15s',
              }}
              onFocus={(e) => (e.target.style.borderColor = '#6366f1')}
              onBlur={(e) => (e.target.style.borderColor = t.border)}
            />
          </div>
          {/* Filter pills */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {FILTER_TABS.map((tab) => (
              <FilterPill
                key={tab.key}
                label={tab.label}
                active={activeFilter === tab.key}
                onClick={() => setActiveFilter(tab.key)}
                t={t}
              />
            ))}
          </div>
        </section>

        {/* Issues Table */}
        <section
          style={{
            background: t.surface,
            borderRadius: 12,
            overflow: 'hidden',
            boxShadow: t.shadowLg,
            border: `1px solid ${t.border}`,
          }}
        >
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 14,
            }}
          >
            <thead>
              <tr
                style={{
                  borderBottom: `1px solid ${t.border}`,
                  textAlign: 'left',
                }}
              >
                {['Issue #', 'Title', 'Age', 'Complexity', 'Status'].map((h, idx) => (
                  <th
                    key={h}
                    style={{
                      padding: '12px 16px',
                      fontSize: 12,
                      fontWeight: 600,
                      color: t.textSecondary,
                      textTransform: 'uppercase',
                      letterSpacing: 0.5,
                      whiteSpace: 'nowrap',
                      ...(idx === 0 ? { paddingLeft: 24, width: 90 } : {}),
                      ...(idx === 2 ? { width: 70 } : {}),
                      ...(idx === 3 ? { width: 110 } : {}),
                      ...(idx === 4 ? { width: 120 } : {}),
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    style={{
                      padding: '40px 16px',
                      textAlign: 'center',
                      color: t.textMuted,
                      fontSize: 14,
                    }}
                  >
                    No issues match your filters.
                  </td>
                </tr>
              )}
              {filtered.map((issue) => {
                const isExpanded = expandedId === issue.id;
                return (
                  <React.Fragment key={issue.id}>
                    <tr
                      onClick={() => setExpandedId(isExpanded ? null : issue.id)}
                      style={{
                        borderBottom: isExpanded ? 'none' : `1px solid ${t.border}`,
                        cursor: 'pointer',
                        transition: 'background 0.12s',
                        background: isExpanded ? (dark ? '#14161e' : '#f8f9fb') : 'transparent',
                      }}
                      onMouseEnter={(e) => {
                        if (!isExpanded) e.currentTarget.style.background = t.surfaceHover;
                      }}
                      onMouseLeave={(e) => {
                        if (!isExpanded) e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      {/* Issue # */}
                      <td style={{ padding: '14px 16px 14px 24px', fontWeight: 600, color: t.textMuted, fontVariantNumeric: 'tabular-nums' }}>
                        #{issue.id}
                      </td>
                      {/* Title + labels */}
                      <td style={{ padding: '14px 16px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          <span style={{ fontWeight: 500, color: t.text, lineHeight: 1.35 }}>{issue.title}</span>
                          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                            {issue.labels.map((l) => (
                              <LabelBadge key={l} label={l} t={t} />
                            ))}
                          </div>
                        </div>
                      </td>
                      {/* Age */}
                      <td style={{ padding: '14px 16px', color: t.textSecondary, fontVariantNumeric: 'tabular-nums' }}>{issue.age}</td>
                      {/* Complexity */}
                      <td style={{ padding: '14px 16px' }}>
                        <ComplexityBadge complexity={issue.complexity} dark={dark} />
                      </td>
                      {/* Status */}
                      <td style={{ padding: '14px 16px' }}>
                        <StatusBadge status={issue.status} dark={dark} />
                      </td>
                    </tr>
                    {isExpanded && <ExpandedRow issue={issue} dark={dark} t={t} onAction={handleAction} />}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  );
}
