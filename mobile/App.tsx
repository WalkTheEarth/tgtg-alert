/**
 * App root.
 *
 * Two states: unpaired (setup) and paired (the tabs). The split lives here
 * rather than inside a screen so the navigation tree itself swaps -- there is no
 * route into the tabs without a server to talk to.
 */

import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { StatusBar } from 'expo-status-bar';
import React, { useEffect } from 'react';
import { Text } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ConnectionProvider, useConnection, useConnectionState } from './src/ConnectionContext';
import type { RootStackParamList, TabParamList } from './src/navigation';
import { currentPushToken, installNotificationHandler } from './src/notifications';
import ActivityScreen from './src/screens/ActivityScreen';
import DiscoverScreen from './src/screens/DiscoverScreen';
import SettingsScreen from './src/screens/SettingsScreen';
import SetupScreen from './src/screens/SetupScreen';
import WatchFormScreen from './src/screens/WatchFormScreen';
import WatchesScreen from './src/screens/WatchesScreen';
import { colors } from './src/theme';

const Tab = createBottomTabNavigator<TabParamList>();
const Stack = createNativeStackNavigator<RootStackParamList>();

const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.bg,
    card: colors.surface,
    text: colors.text,
    border: colors.border,
    primary: colors.accent,
  },
};

const screenHeader = {
  headerStyle: { backgroundColor: colors.surface },
  headerTintColor: colors.text,
  headerTitleStyle: { fontWeight: '600' as const },
};

function TabIcon({ label, focused }: { label: string; focused: boolean }) {
  // Text glyphs rather than an icon font: one less dependency, and it renders
  // identically on both platforms.
  const glyphs: Record<string, string> = {
    Watches: '◎',
    Discover: '⌕',
    Activity: '◔',
    Settings: '⚙',
  };
  return (
    <Text style={{ fontSize: 20, color: focused ? colors.accent : colors.textFaint }}>
      {glyphs[label] ?? '•'}
    </Text>
  );
}

function Tabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        ...screenHeader,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textFaint,
        tabBarIcon: ({ focused }) => <TabIcon label={route.name} focused={focused} />,
      })}
    >
      <Tab.Screen name="Watches" component={WatchesScreen} />
      <Tab.Screen name="Discover" component={DiscoverScreen} />
      <Tab.Screen name="Activity" component={ActivityScreen} />
      <Tab.Screen name="Settings" component={SettingsScreen} />
    </Tab.Navigator>
  );
}

function Root() {
  const { client, connection } = useConnection();

  // Re-register the push token on every launch. Tokens rotate on reinstall and
  // occasionally on their own; the server upserts, so this costs nothing.
  useEffect(() => {
    if (!client) return;
    (async () => {
      const token = await currentPushToken();
      if (!token) return;
      try {
        await client.registerDevice(token, 'mobile', 'This phone');
      } catch {
        // Non-fatal: the app is still usable, and Settings can retry.
      }
    })();
  }, [client]);

  return (
    <Stack.Navigator screenOptions={screenHeader}>
      <Stack.Screen name="Tabs" component={Tabs} options={{ headerShown: false }} />
      <Stack.Screen
        name="WatchForm"
        component={WatchFormScreen}
        options={({ route }) => ({
          title: route.params?.watchId ? 'Edit watch' : 'New watch',
          presentation: 'modal',
        })}
      />
    </Stack.Navigator>
  );
}

function Gate() {
  // The provider already blocks on `ready` and renders a spinner, so by the
  // time this mounts the answer is final.
  const { connection } = useConnectionState();
  return connection ? <Root /> : <SetupScreen />;
}

export default function App() {
  useEffect(() => {
    installNotificationHandler();
  }, []);

  return (
    <SafeAreaProvider>
      <ConnectionProvider>
        <NavigationContainer theme={navTheme}>
          <StatusBar style="light" />
          <Gate />
        </NavigationContainer>
      </ConnectionProvider>
    </SafeAreaProvider>
  );
}
