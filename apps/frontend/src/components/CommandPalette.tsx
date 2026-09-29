import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { CaseQueueEntry } from '../api/types';
import { useAuth } from '../store/auth';

/**
 * Global navigation and action palette.
 *
 * Deliberately distinct from the AEGIS Agent, which answers questions about the
 * current workspace. This surface only *moves* and *acts*: it is a command
 * line over the app's own routes. ⌘K is bound by the shell (see
 * `openCommandPalette`); nothing here installs a global key listener, so the
 * shortcut is declared in exactly one place.
 */

export type CommandKind = 'navigation' | 'case' | 'action';

export interface PaletteCommand {
  readonly id: string;
  readonly kind: CommandKind;
  readonly label: string;
  readonly group: string;
  /** Extra terms matched by the filter but never displayed as the label. */
  readonly keywords: readonly string[];
  readonly hint?: string;
  /** Navigation commands carry a path; actions are executed by the palette. */
  readonly path?: string;
  readonly run?: () => void | Promise<void>;
}

const NAVIGATION: ReadonlyArray<Omit<PaletteCommand, 'id' | 'kind' | 'group'>> = [
  { label: 'Command Center', path: '/', keywords: ['home', 'dashboard', 'overview', 'start'], hint: 'Live posture across every investigation' },
  { label: 'Investigations', path: '/cases', keywords: ['cases', 'register', 'queue', 'search'], hint: 'Investigations register and priority queue' },
  { label: 'Threat Watch', path: '/threat-watch', keywords: ['live', 'feed', 'events', 'monitor'], hint: 'Continuous monitoring channel' },
  { label: 'Reports', path: '/reports', keywords: ['report', 'export', 'brief', 'pdf'], hint: 'Preview and export case reports' },
  { label: 'Administration', path: '/admin', keywords: ['admin', 'team', 'audit', 'system', 'settings'], hint: 'Team, audit trail and system health' },
];

/**
 * Build the static command list.
 *
 * Cases come from the API rather than a fixture, so the palette never offers
 * navigation to a case that has been closed out from under the analyst. The
 * caller decides when to refresh; the palette itself never fetches on render.
 */
export function buildCommands(cases: readonly CaseQueueEntry[]): readonly PaletteCommand[] {
  const navigation: PaletteCommand[] = NAVIGATION.map((entry, index) => ({
    id: `nav:${entry.path ?? index}`,
    kind: 'navigation',
    group: 'Navigate',
    ...entry,
  }));

  const caseCommands: PaletteCommand[] = cases.map((item) => ({
    id: `case:${item.case_id}`,
    kind: 'case',
    group: 'Investigations',
    label: item.name,
    keywords: [item.case_id, item.status, item.priority, item.severity, ...item.tags],
    hint: `${item.status.replace('_', ' ')} · ${item.priority} · ${item.counts.evidence} evidence`,
    path: `/cases/${item.case_id}`,
  }));

  const actions: PaletteCommand[] = [
    {
      id: 'action:refresh',
      kind: 'action',
      group: 'Actions',
      label: 'Refresh workspace data',
      keywords: ['reload', 'sync', 'update', 'data'],
      hint: 'Re-read the current screen from the API',
      run: () => {
        window.dispatchEvent(new CustomEvent('aegis:refresh'));
        window.location.reload();
      },
    },
    {
      id: 'action:diagnostics',
      kind: 'action',
      group: 'Actions',
      label: 'Copy diagnostics',
      keywords: ['debug', 'clipboard', 'support', 'info', 'health'],
      hint: 'Copy route, session and API details to the clipboard',
      run: () => {
        const token = window.localStorage.getItem('aegis.apiKey');
        void navigator.clipboard?.writeText(
          [
            `AEGIS diagnostics — ${new Date().toISOString()}`,
            `route: ${window.location.pathname}`,
            `origin: ${window.location.origin}`,
            `user agent: ${window.navigator.userAgent}`,
            `api key configured: ${token === null ? 'no' : 'yes'}`,
            `localStorage keys: ${Object.keys(window.localStorage).join(', ') || 'none'}`,
          ].join('\n'),
        );
      },
    },
    {
      // The handler is bound by {@link withSignOut} once the auth store is
      // readable, so the list itself stays independent of the store.
      id: 'action:sign-out',
      kind: 'action',
      group: 'Actions',
      label: 'Sign out',
      keywords: ['logout', 'exit', 'end session', 'lock'],
      hint: 'Clear the analyst session from this browser',
    },
  ];

  return [...navigation, ...caseCommands, ...actions];
}

/** Bind the sign-out command to the auth store without duplicating the list. */
function withSignOut(commands: readonly PaletteCommand[], signOut: () => void): readonly PaletteCommand[] {
  return commands.map((command) =>
    command.id === 'action:sign-out' ? { ...command, run: signOut } : command,
  );
}

/**
 * Imperative opener for callers outside the shell (deep links, empty states).
 * The shell registers its own setter on mount; until then `open()` is a no-op
 * rather than an error, so a stale call cannot crash a render.
 */
let paletteOpener: (() => void) | null = null;

export const openCommandPalette: {
  set(opener: (() => void) | null): void;
  open(): void;
} = {
  set(opener) {
    paletteOpener = opener;
  },
  open() {
    paletteOpener?.();
  },
};

/**
 * Subsequence match with a crude score.
 *
 * Consecutive hits and word-boundary hits rank higher, which is enough to put
 * "Threat Watch" above "Watch the evidence" for the query `watch` without
 * pulling in a fuzzy-matching dependency.
 */
function score(command: PaletteCommand, query: string): number {
  const needle = query.toLowerCase();
  const haystack = `${command.label} ${command.keywords.join(' ')}`.toLowerCase();
  const direct = command.label.toLowerCase().indexOf(needle);
  if (direct === 0) return 1000 - command.label.length;
  if (direct > 0) return 700 - direct;
  let cursor = 0;
  let hits = 0;
  let streak = 0;
  let best = 0;
  for (const character of needle) {
    const found = haystack.indexOf(character, cursor);
    if (found === -1) return 0;
    streak = found === cursor ? streak + 1 : 0;
    hits += 1 + streak;
    cursor = found + 1;
  }
  if (hits === 0) return 0;
  best += 500 - haystack.length;
  return best + hits;
}

function filterCommands(commands: readonly PaletteCommand[], query: string): readonly PaletteCommand[] {
  const trimmed = query.trim();
  if (trimmed === '') return commands;
  return commands
    .map((command) => ({ command, rank: score(command, trimmed) }))
    .filter((entry) => entry.rank > 0)
    .sort((a, b) => b.rank - a.rank || a.command.label.localeCompare(b.command.label))
    .map((entry) => entry.command);
}

/** Group headers in the order they first appear, so a filtered list still reads top-down. */
function groupOrder(commands: readonly PaletteCommand[]): readonly string[] {
  const seen: string[] = [];
  for (const command of commands) if (!seen.includes(command.group)) seen.push(command.group);
  return seen;
}

function useCases(): readonly CaseQueueEntry[] {
  const [cases, setCases] = useState<readonly CaseQueueEntry[]>([]);

  useEffect(() => {
    let active = true;
    api
      .caseSummaries()
      .then((rows) => {
        if (active) setCases(rows);
      })
      .catch(() => {
        // A failed case lookup must not take navigation down: the palette is
        // still useful for the static routes and actions.
        if (active) setCases([]);
      });
    return () => {
      active = false;
    };
  }, []);

  return cases;
}

export interface CommandPaletteProps {
  readonly open: boolean;
  readonly onClose: () => void;
  /** Optional override; when absent the palette runs the command itself. */
  readonly onRun?: (commandId: string) => void;
}

export function CommandPalette({ open, onClose, onRun }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const cases = useCases();
  const commands = useMemo(() => withSignOut(buildCommands(cases), signOut), [cases, signOut]);

  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const results = useMemo(() => filterCommands(commands, query), [commands, query]);

  // Option ids follow the *filtered* list, so `aria-activedescendant` always
  // points at the row currently rendered at the highlight index.
  const optionIds = useMemo(
    () => results.map((_, index) => `${listId}-option-${index}`),
    [results, listId],
  );

  // A fresh query must not leave the highlight pointing past the end of a
  // shorter result set.
  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (!open) return undefined;
    setQuery('');
    setActiveIndex(0);
    const previous = document.activeElement;
    inputRef.current?.focus();
    return () => {
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const clamped = Math.min(activeIndex, Math.max(0, results.length - 1));
    if (clamped !== activeIndex) setActiveIndex(clamped);
  }, [activeIndex, open, results.length]);

  const run = useCallback(
    (command: PaletteCommand) => {
      onClose();
      onRun?.(command.id);
      if (command.path !== undefined) {
        void navigate(command.path);
        return;
      }
      void command.run?.();
    },
    [navigate, onClose, onRun],
  );

  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === 'Tab') {
        // The palette is modal and its only focusable control is the input, so
        // Tab is held here rather than escaping into the page behind it.
        event.preventDefault();
        inputRef.current?.focus();
        return;
      }
      if (results.length === 0) return;
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActiveIndex((index) => (index + 1) % results.length);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActiveIndex((index) => (index - 1 + results.length) % results.length);
      } else if (event.key === 'Home') {
        event.preventDefault();
        setActiveIndex(0);
      } else if (event.key === 'End') {
        event.preventDefault();
        setActiveIndex(results.length - 1);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        const command = results[activeIndex];
        if (command) run(command);
      }
    },
    [activeIndex, onClose, results, run],
  );

  if (!open) return null;

  const groups = groupOrder(results);
  const activeId = optionIds[activeIndex];
  const dialogTitleId = `${listId}-title`;

  return createPortal(
    <div
      className="pal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="pal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={dialogTitleId}
        ref={dialogRef}
        onKeyDown={onKeyDown}
      >
        <h2 className="pal-visually-hidden" id={dialogTitleId}>
          Command palette
        </h2>
        <div className="pal-input">
          <span className="pal-input__icon" aria-hidden="true">
            ⌕
          </span>
          <input
            ref={inputRef}
            className="pal-input__field"
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls={`${listId}-list`}
            aria-activedescendant={activeId}
            aria-autocomplete="list"
            aria-label="Search commands and investigations"
            placeholder="Search commands, investigations and actions…"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <kbd className="pal-input__kbd" aria-hidden="true">
            Esc
          </kbd>
        </div>

        <ul className="pal-list" id={`${listId}-list`} role="listbox" aria-label="Commands">
          {results.length === 0 ? (
            <li className="pal-empty" role="presentation">
              No command matches “{query.trim()}”.
            </li>
          ) : (
            groups.map((group) => (
              <li className="pal-group" key={group} role="presentation">
                <p className="pal-group__label" aria-hidden="true">
                  {group}
                </p>
                <ul className="pal-group__items" role="group" aria-label={group}>
                  {results.map((command, index) =>
                    command.group === group ? (
                      <li
                        key={command.id}
                        id={optionIds[index]}
                        role="option"
                        aria-selected={index === activeIndex}
                        className={index === activeIndex ? 'pal-option pal-option--active' : 'pal-option'}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => run(command)}
                        onMouseDown={(event) => event.preventDefault()}
                      >
                        <span className="pal-option__icon" aria-hidden="true">
                          {command.kind === 'case' ? '◎' : command.kind === 'navigation' ? '⌂' : '⚡'}
                        </span>
                        <span className="pal-option__text">
                          <b>{command.label}</b>
                          {command.hint !== undefined && <small>{command.hint}</small>}
                        </span>
                        <kbd className="pal-option__kbd" aria-hidden="true">
                          ↵
                        </kbd>
                      </li>
                    ) : null,
                  )}
                </ul>
              </li>
            ))
          )}
        </ul>

        <footer className="pal-foot">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> move
          </span>
          <span>
            <kbd>↵</kbd> run
          </span>
          <span>
            <kbd>Home</kbd>
            <kbd>End</kbd> jump
          </span>
          <span className="pal-foot__count" role="status">
            {results.length} of {commands.length}
          </span>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
