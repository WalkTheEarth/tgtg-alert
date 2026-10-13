/**
 * Navigation types, kept in one place so screens can import them without
 * creating cycles with App.tsx.
 *
 * The tab screens are wrapped in a native stack that owns the modal watch form.
 * That nesting is why the screens use `CompositeScreenProps`: their own props
 * come from the tab navigator, but they also need to push onto the parent
 * stack. Getting this right is what makes `navigation.navigate('WatchForm')`
 * typecheck from inside a tab.
 */

import type { BottomTabScreenProps } from '@react-navigation/bottom-tabs';
import type { CompositeScreenProps } from '@react-navigation/native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';

export type RootStackParamList = {
  Tabs: undefined;
  WatchForm: {
    /** Omit to create; pass an id to edit. */
    watchId?: number;
    /** Prefill when arriving from a Discover result. */
    prefill?: {
      storeName?: string;
      bagName?: string;
      latitude?: number;
      longitude?: number;
    };
  };
};

export type TabParamList = {
  Watches: undefined;
  Discover: undefined;
  Activity: undefined;
  Settings: undefined;
};

/** Props for a screen that lives in a tab but can push onto the root stack. */
export type TabScreenProps<T extends keyof TabParamList> = CompositeScreenProps<
  BottomTabScreenProps<TabParamList, T>,
  NativeStackScreenProps<RootStackParamList>
>;

export type WatchFormProps = NativeStackScreenProps<RootStackParamList, 'WatchForm'>;
