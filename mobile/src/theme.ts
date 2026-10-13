/** Design tokens. One place to change the look. */

export const colors = {
  bg: '#0F1115',
  surface: '#171A21',
  surfaceAlt: '#1F232C',
  border: '#2A2F3A',
  text: '#F2F4F8',
  textMuted: '#9AA3B2',
  textFaint: '#6B7280',
  accent: '#00C48C',
  accentDim: '#0B3B2E',
  warn: '#F5A524',
  warnDim: '#3A2A0B',
  danger: '#F04E4E',
  dangerDim: '#3A1414',
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
};

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  pill: 999,
};

export const type = {
  title: { fontSize: 28, fontWeight: '700' as const, color: colors.text },
  heading: { fontSize: 18, fontWeight: '600' as const, color: colors.text },
  body: { fontSize: 15, color: colors.text },
  label: { fontSize: 13, fontWeight: '600' as const, color: colors.textMuted },
  caption: { fontSize: 12, color: colors.textFaint },
};
