import { CaseExportMenu } from './CaseExportMenu';

/**
 * Ready-made export control for the Investigations register header.
 *
 * The register spans many cases and none of them is "the" case, so the menu
 * opens on "All investigations" rather than defaulting to a single case. It
 * owns its own open/closed state and takes no props — render it directly in
 * the register header beside the "New investigation" action.
 */
export function RegisterExportButton() {
  // An empty caseId tells CaseExportMenu there is no case in focus, so the
  // selector starts on "All investigations".
  return <CaseExportMenu caseId="" />;
}
