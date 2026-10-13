/** Small reusable pieces, so the screens stay about behaviour. */

import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from 'react-native';

import { colors, radius, spacing, type } from './theme';

export function Button({
  title,
  onPress,
  variant = 'primary',
  loading = false,
  disabled = false,
  style,
}: {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
}) {
  const isDisabled = disabled || loading;

  const background =
    variant === 'primary'
      ? colors.accent
      : variant === 'danger'
        ? colors.dangerDim
        : variant === 'secondary'
          ? colors.surfaceAlt
          : 'transparent';

  const textColor =
    variant === 'primary'
      ? '#04231A'
      : variant === 'danger'
        ? colors.danger
        : variant === 'secondary'
          ? colors.text
          : colors.accent;

  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: background, opacity: isDisabled ? 0.5 : pressed ? 0.8 : 1 },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={textColor} size="small" />
      ) : (
        <Text style={[styles.buttonText, { color: textColor }]}>{title}</Text>
      )}
    </Pressable>
  );
}

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Field({
  label,
  hint,
  ...props
}: TextInputProps & { label: string; hint?: string }) {
  return (
    <View style={{ marginBottom: spacing.lg }}>
      <Text style={[type.label, { marginBottom: spacing.xs }]}>{label}</Text>
      <TextInput
        {...props}
        placeholderTextColor={colors.textFaint}
        style={[styles.input, props.style]}
      />
      {hint ? (
        <Text style={[type.caption, { marginTop: spacing.xs }]}>{hint}</Text>
      ) : null}
    </View>
  );
}

export function Badge({
  text,
  tone = 'neutral',
}: {
  text: string;
  tone?: 'neutral' | 'good' | 'warn' | 'bad';
}) {
  const tones = {
    neutral: { bg: colors.surfaceAlt, fg: colors.textMuted },
    good: { bg: colors.accentDim, fg: colors.accent },
    warn: { bg: colors.warnDim, fg: colors.warn },
    bad: { bg: colors.dangerDim, fg: colors.danger },
  } as const;
  const { bg, fg } = tones[tone];
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={{ color: fg, fontSize: 11, fontWeight: '600' }}>{text}</Text>
    </View>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <View style={styles.empty}>
      <Text style={[type.heading, { marginBottom: spacing.sm, textAlign: 'center' }]}>
        {title}
      </Text>
      <Text
        style={[
          type.body,
          { color: colors.textMuted, textAlign: 'center', marginBottom: spacing.xl },
        ]}
      >
        {body}
      </Text>
      {action}
    </View>
  );
}

export function Banner({
  tone,
  title,
  body,
}: {
  tone: 'good' | 'warn' | 'bad' | 'info';
  title: string;
  body?: string;
}) {
  const map = {
    good: { bg: colors.accentDim, fg: colors.accent },
    warn: { bg: colors.warnDim, fg: colors.warn },
    bad: { bg: colors.dangerDim, fg: colors.danger },
    info: { bg: colors.surfaceAlt, fg: colors.textMuted },
  } as const;
  const { bg, fg } = map[tone];
  return (
    <View style={[styles.banner, { backgroundColor: bg }]}>
      <Text style={{ color: fg, fontWeight: '600', fontSize: 13 }}>{title}</Text>
      {body ? (
        <Text style={{ color: fg, fontSize: 12, marginTop: 3, opacity: 0.85 }}>{body}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  button: {
    paddingVertical: spacing.md + 2,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 48,
  },
  buttonText: { fontSize: 15, fontWeight: '600' },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  input: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    color: colors.text,
    fontSize: 15,
    borderWidth: 1,
    borderColor: colors.border,
  },
  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.pill,
    alignSelf: 'flex-start',
  },
  empty: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
  },
  banner: {
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
});
