import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  Kbd,
  Modal,
  NavLink,
  ScrollArea,
  Table,
  Text,
  ThemeIcon,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconActivity,
  IconBooks,
  IconCalendar,
  IconDeviceDesktopAnalytics,
  IconKeyboard,
  IconMoon,
  IconSun,
  IconSunMoon,
  IconNews,
  IconSearch,
  IconSettings,
  type Icon,
} from '@tabler/icons-react';
import { useCallback, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { useUnmappedFiles } from '../api/settings';
import { useHealth } from '../api/systemPages';
import { t, type MessageKey } from '../i18n';
import { GO_TO, useShortcuts } from './shortcuts';

interface NavChild {
  label: MessageKey;
  to: string;
  /** Extra path prefixes that also mark this entry active. */
  matches?: string[];
  /** Show a count next to the label. */
  count?: 'unmapped' | 'health';
}

interface NavItem extends NavChild {
  icon: Icon;
  children?: NavChild[];
}

const NAV_ITEMS: NavItem[] = [
  {
    label: 'nav.library',
    to: '/library',
    matches: ['/magazine'],
    icon: IconBooks,
    children: [
      { label: 'nav.library.magazines', to: '/library', matches: ['/magazine'] },
      { label: 'nav.library.add', to: '/library/add' },
      { label: 'nav.library.import', to: '/library/import' },
      { label: 'nav.library.unmapped', to: '/library/unmapped', count: 'unmapped' },
    ],
  },
  { label: 'nav.calendar', to: '/calendar', icon: IconCalendar },
  {
    label: 'nav.activity',
    to: '/activity',
    icon: IconActivity,
    children: [
      { label: 'nav.activity.queue', to: '/activity/queue' },
      { label: 'nav.activity.history', to: '/activity/history' },
      { label: 'nav.activity.import', to: '/activity/import' },
    ],
  },
  { label: 'nav.wanted', to: '/wanted', icon: IconSearch },
  {
    label: 'nav.settings',
    to: '/settings',
    icon: IconSettings,
    children: [
      { label: 'nav.settings.media', to: '/settings/mediamanagement' },
      { label: 'nav.settings.profiles', to: '/settings/profiles' },
      { label: 'nav.settings.indexers', to: '/settings/indexers' },
      { label: 'nav.settings.clients', to: '/settings/downloadclients' },
      { label: 'nav.settings.automation', to: '/settings/automation' },
      { label: 'nav.settings.notifications', to: '/settings/notifications' },
    ],
  },
  {
    label: 'nav.system',
    to: '/system',
    icon: IconDeviceDesktopAnalytics,
    count: 'health',
    children: [
      { label: 'nav.system.status', to: '/system/status' },
      { label: 'nav.system.health', to: '/system/health', count: 'health' },
      { label: 'nav.system.tasks', to: '/system/tasks' },
      { label: 'nav.system.backup', to: '/system/backup' },
      { label: 'nav.system.logs', to: '/system/logs' },
    ],
  },
];

function isUnder(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function sectionActive(pathname: string, item: NavChild): boolean {
  return [item.to, ...(item.matches ?? [])].some((prefix) => isUnder(pathname, prefix));
}

/** How many files the last library scan couldn't place; nothing when there are none. */
function UnmappedCount() {
  const { data } = useUnmappedFiles();
  if (!data?.length) return null;
  return (
    <Badge size="sm" variant="light" color="orange" aria-label={t('nav.library.unmapped.count', { count: data.length })}>
      {data.length}
    </Badge>
  );
}

/** Health problems (errors and warnings, not notices); red when anything is an error. */
function HealthCount() {
  const { data } = useHealth();
  const problems = (data?.items ?? []).filter((i) => i.level !== 'notice');
  if (!problems.length) return null;
  return (
    <Badge
      size="sm"
      variant="light"
      color={problems.some((p) => p.level === 'error') ? 'red' : 'orange'}
      aria-label={t('nav.system.health.count', { count: problems.length })}
    >
      {problems.length}
    </Badge>
  );
}

function Count({ kind }: { kind: NavChild['count'] }) {
  if (kind === 'unmapped') return <UnmappedCount />;
  if (kind === 'health') return <HealthCount />;
  return null;
}

const SCHEMES = ['dark', 'light', 'auto'] as const;
const SCHEME_ICONS = { dark: IconMoon, light: IconSun, auto: IconSunMoon };

function Shortcuts({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const rows: [string[], string][] = [
    [['?'], t('shortcuts.help')],
    [['/'], t('shortcuts.search')],
    [['n'], t('shortcuts.add')],
    [['t'], t('shortcuts.theme')],
    ...GO_TO.map((g): [string[], string] => [['g', g.key], t('shortcuts.goTo', { section: t(g.label) })]),
  ];
  return (
    <Modal opened={opened} onClose={onClose} title={t('shortcuts.title')}>
      <Table verticalSpacing={6}>
        <Table.Tbody>
          {rows.map(([keys, label]) => (
            <Table.Tr key={keys.join(' ')}>
              <Table.Td w={90}>
                {keys.map((k, i) => (
                  <span key={k}>
                    {i > 0 && ' '}
                    <Kbd>{k}</Kbd>
                  </span>
                ))}
              </Table.Td>
              <Table.Td>{label}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Modal>
  );
}

function childActive(pathname: string, child: NavChild): boolean {
  return pathname === child.to || (child.matches ?? []).some((p) => isUnder(pathname, p));
}

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [help, setHelp] = useState(false);
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const nextScheme = useCallback(
    () => setColorScheme(SCHEMES[(SCHEMES.indexOf(colorScheme) + 1) % SCHEMES.length]!),
    [colorScheme, setColorScheme],
  );
  const openHelp = useCallback(() => setHelp(true), []);
  useShortcuts({ onHelp: openHelp, onTheme: nextScheme });
  const SchemeIcon = SCHEME_ICONS[colorScheme];

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header>
        <Group h="100%" px="md" gap="sm">
          <Burger
            opened={opened}
            onClick={toggle}
            hiddenFrom="sm"
            size="sm"
            aria-label={t('nav.toggle')}
          />
          <ThemeIcon variant="filled" size="md" radius="sm">
            <IconNews size={18} stroke={1.8} />
          </ThemeIcon>
          <Text fw={700} size="lg">
            {t('app.name')}
          </Text>
          <Group gap={4} ml="auto">
            <Tooltip label={t(`theme.${colorScheme}`)}>
              <ActionIcon variant="subtle" color="gray" size="lg" aria-label={t('theme.toggle', { scheme: t(`theme.${colorScheme}`) })} onClick={nextScheme}>
                <SchemeIcon size={18} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label={t('shortcuts.title')}>
              <ActionIcon variant="subtle" color="gray" size="lg" aria-label={t('shortcuts.title')} onClick={openHelp} visibleFrom="sm">
                <IconKeyboard size={18} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs" aria-label="Main">
        <ScrollArea>
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = sectionActive(pathname, item);
            const target = item.children?.[0]?.to ?? item.to;
            return (
              <NavLink
                key={item.to}
                component={Link}
                to={target}
                label={t(item.label)}
                leftSection={<Icon size={20} stroke={1.6} />}
                // Shown while the section is closed; inside it the child entry carries the count.
                rightSection={item.count && !active ? <Count kind={item.count} /> : undefined}
                active={active}
                opened={item.children ? active : undefined}
                onClick={() => {
                  // Mantine cancels the link's navigation for entries with children (it
                  // treats them as collapsible groups), so navigate explicitly. The group
                  // then expands because its section becomes active.
                  if (item.children) navigate(target);
                  close();
                }}
              >
                {item.children?.map((child) => (
                  <NavLink
                    key={child.to}
                    component={Link}
                    to={child.to}
                    label={t(child.label)}
                    rightSection={child.count && active ? <Count kind={child.count} /> : undefined}
                    active={childActive(pathname, child)}
                    aria-current={childActive(pathname, child) ? 'page' : undefined}
                    onClick={close}
                  />
                ))}
              </NavLink>
            );
          })}
        </ScrollArea>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
      <Shortcuts opened={help} onClose={() => setHelp(false)} />
    </AppShell>
  );
}
