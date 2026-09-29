import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';

export type InspectorTone = 'ok' | 'warn' | 'danger' | 'muted';

export interface InspectorStatus {
  readonly label: string;
  readonly tone: InspectorTone;
}

export interface InspectorFact {
  readonly label: string;
  readonly value: ReactNode;
  readonly mono?: boolean;
}

export interface InspectorIdentifier {
  readonly kind: string;
  readonly value: string;
}

export interface InspectorConfidence {
  readonly value: number;
  readonly kind: 'recorded' | 'estimate';
}

export interface InspectorTab {
  readonly id: string;
  readonly label: string;
}

export interface InspectorRailProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly title: string;
  readonly subtitle?: string;
  readonly status?: readonly InspectorStatus[];
  readonly facts: readonly InspectorFact[];
  readonly identifiers?: readonly InspectorIdentifier[];
  readonly confidence?: InspectorConfidence;
  readonly summary?: string;
  readonly tabs?: readonly InspectorTab[];
  readonly activeTab?: string;
  readonly onTabChange?: (id: string) => void;
  readonly tabPanels?: Readonly<Record<string, ReactNode>>;
  readonly actions?: ReactNode;
  readonly empty?: string;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A confidence figure is never presented as a bare percentage: the number says
 * how strong the signal is, the badge says where the number came from. A 70%
 * the platform measured and a 70% a model guessed are not the same claim, and an
 * analyst acting on one of them deserves to know which it is.
 */
const CONFIDENCE_KIND_LABEL: Record<InspectorConfidence['kind'], string> = {
  recorded: 'Recorded score',
  estimate: 'Model estimate',
};

/**
 * Persistent right-hand inspector rail.
 *
 * The rail never navigates and never unmounts the surface behind it — selecting
 * something fills the rail in place while the list stays where it was. That is
 * the whole point: an analyst chasing a relationship keeps the register, the
 * filters and the sort in view instead of reconstructing them from memory after
 * a page transition.
 *
 * It is a `complementary` landmark rather than a dialog: it is not modal, the
 * register behind it stays operable, and screen readers should be able to reach
 * both. Focus still moves into the rail on open (so a keyboard user does not
 * have to hunt for it), is trapped while it is open (so Tab does not wander into
 * a list that is now visually narrower), and is returned to the trigger on close.
 */
export function InspectorRail({
  open,
  onClose,
  title,
  subtitle,
  status,
  facts,
  identifiers,
  confidence,
  summary,
  tabs,
  activeTab,
  onTabChange,
  tabPanels,
  actions,
  empty,
}: InspectorRailProps) {
  const titleId = useId();
  const railRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Focus in on open, Escape + Tab trap while open, focus back out on close.
  // Keyed on `open` alone: re-running on every prop change would yank focus out
  // of whatever the analyst was reading inside the rail.
  useEffect(() => {
    if (!open) return undefined;
    const restore = document.activeElement;
    headingRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const rail = railRef.current;
      if (rail === null) return;
      const stops = [...rail.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (element) => element.offsetParent !== null || element === document.activeElement,
      );
      if (stops.length === 0) {
        event.preventDefault();
        return;
      }
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (first === undefined || last === undefined) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (restore instanceof HTMLElement) restore.focus();
    };
  }, [open]);

  if (!open) return null;

  const hasContent =
    facts.length > 0 ||
    (status !== undefined && status.length > 0) ||
    (identifiers !== undefined && identifiers.length > 0) ||
    confidence !== undefined ||
    summary !== undefined ||
    (tabs !== undefined && tabs.length > 0) ||
    actions !== undefined;

  const resolvedTab = activeTab ?? tabs?.[0]?.id;

  return (
    <aside
      className="insp-rail"
      ref={railRef}
      role="complementary"
      aria-label={title}
      data-open="true"
    >
      <header className="insp-rail__head">
        <div className="insp-rail__heading">
          <h2 className="insp-rail__title" id={titleId} tabIndex={-1} ref={headingRef}>
            {title}
          </h2>
          {subtitle !== undefined && <p className="insp-rail__subtitle">{subtitle}</p>}
        </div>
        <button
          type="button"
          className="insp-rail__close"
          onClick={onClose}
          aria-label="Close inspector"
        >
          <span aria-hidden="true">✕</span>
        </button>
      </header>

      {!hasContent && empty !== undefined ? (
        <div className="insp-rail__body">
          <p className="insp-rail__empty">{empty}</p>
        </div>
      ) : (
        <>
          <div className="insp-rail__body">
            {status !== undefined && status.length > 0 && (
              <ul className="insp-status" aria-label="Status">
                {status.map((item, index) => (
                  <li
                    // Indexed too: priority and severity legitimately share a
                    // label, and React needs the position to keep them apart.
                    key={`${item.tone}:${item.label}:${index}`}
                    className={`insp-status__pill insp-status__pill--${item.tone}`}
                  >
                    <span className="insp-status__dot" aria-hidden="true" />
                    {item.label}
                  </li>
                ))}
              </ul>
            )}

            {summary !== undefined && <p className="insp-rail__summary">{summary}</p>}

            {confidence !== undefined && (
              <section className="insp-confidence" aria-label="Confidence">
                <div className="insp-confidence__head">
                  <span className="insp-label">Confidence</span>
                  <span className="insp-confidence__value">{`${Math.round(confidence.value * 1000) / 10}%`}</span>
                </div>
                <div
                  className="insp-confidence__bar"
                  role="meter"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(Math.min(1, Math.max(0, confidence.value)) * 100)}
                  aria-valuetext={`${Math.round(Math.min(1, Math.max(0, confidence.value)) * 1000) / 10}% ${CONFIDENCE_KIND_LABEL[confidence.kind]}`}
                >
                  <i
                    className="insp-confidence__fill"
                    style={{ width: `${Math.round(Math.min(1, Math.max(0, confidence.value)) * 100)}%` }}
                  />
                </div>
                <span className={`insp-confidence__badge insp-confidence__badge--${confidence.kind}`}>
                  {CONFIDENCE_KIND_LABEL[confidence.kind]}
                </span>
              </section>
            )}

            {facts.length > 0 && (
              <dl className="insp-facts">
                {facts.map((fact) => (
                  <div className="insp-facts__row" key={fact.label}>
                    <dt className="insp-facts__label">{fact.label}</dt>
                    <dd className={fact.mono === true ? 'insp-facts__value insp-facts__value--mono' : 'insp-facts__value'}>
                      {fact.value}
                    </dd>
                  </div>
                ))}
              </dl>
            )}

            {identifiers !== undefined && identifiers.length > 0 && (
              <ul className="insp-ids" aria-label="Identifiers">
                {identifiers.map((identifier) => (
                  <li className="insp-ids__chip" key={`${identifier.kind}:${identifier.value}`}>
                    <span className="insp-ids__kind">{identifier.kind}</span>
                    <span className="insp-ids__value">{identifier.value}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {tabs !== undefined && tabs.length > 0 && (
            <div className="insp-rail__tabs">
              <div className="insp-tabs" role="tablist" aria-label="Inspector sections">
                {tabs.map((tab) => {
                  const selected = tab.id === resolvedTab;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      id={`insp-tab-${tab.id}`}
                      aria-selected={selected}
                      aria-controls={`insp-panel-${tab.id}`}
                      tabIndex={selected ? 0 : -1}
                      className={selected ? 'insp-tabs__tab is-active' : 'insp-tabs__tab'}
                      onClick={() => onTabChange?.(tab.id)}
                    >
                      {tab.label}
                    </button>
                  );
                })}
              </div>
              {tabs.map((tab) => (
                <div
                  key={tab.id}
                  role="tabpanel"
                  id={`insp-panel-${tab.id}`}
                  aria-labelledby={`insp-tab-${tab.id}`}
                  hidden={tab.id !== resolvedTab}
                  className="insp-tabs__panel"
                >
                  {tab.id === resolvedTab ? tabPanels?.[tab.id] : null}
                </div>
              ))}
            </div>
          )}

          {actions !== undefined && <footer className="insp-rail__foot">{actions}</footer>}
        </>
      )}
    </aside>
  );
}
