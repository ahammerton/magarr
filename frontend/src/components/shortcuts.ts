import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import type { MessageKey } from '../i18n';

/** "g" then a letter goes to a section, like Gmail and GitHub. */
export const GO_TO: { key: string; to: string; label: MessageKey }[] = [
  { key: 'l', to: '/library', label: 'nav.library' },
  { key: 'c', to: '/calendar', label: 'nav.calendar' },
  { key: 'a', to: '/activity/queue', label: 'nav.activity' },
  { key: 'w', to: '/wanted', label: 'nav.wanted' },
  { key: 's', to: '/settings', label: 'nav.settings' },
  { key: 'y', to: '/system/status', label: 'nav.system' },
];
const SEQUENCE_MS = 1500;

function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

/** Global keyboard shortcuts; ignored while typing in a field. */
export function useShortcuts({ onHelp, onTheme }: { onHelp: () => void; onTheme: () => void }): void {
  const navigate = useNavigate();
  const pendingG = useRef(0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return;
      if (pendingG.current && Date.now() - pendingG.current < SEQUENCE_MS) {
        pendingG.current = 0;
        const target = GO_TO.find((g) => g.key === event.key.toLowerCase());
        if (target) {
          event.preventDefault();
          navigate(target.to);
        }
        return;
      }
      switch (event.key) {
        case 'g':
          pendingG.current = Date.now();
          break;
        case '?':
          event.preventDefault();
          onHelp();
          break;
        case '/': {
          const search = document.querySelector<HTMLInputElement>('[data-shortcut-search]');
          if (search) {
            event.preventDefault();
            search.focus();
          }
          break;
        }
        case 'n':
          navigate('/library/add');
          break;
        case 't':
          onTheme();
          break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate, onHelp, onTheme]);
}
