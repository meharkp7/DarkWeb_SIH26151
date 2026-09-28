import { Link } from 'react-router-dom';
import { Panel } from '../components/Panel';

/** Unknown route fallback. */
export function NotFoundPage() {
  return (
    <div className="stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Page not found</h1>
          <p className="page-sub">That route does not exist in the Investigation Console.</p>
        </div>
      </header>
      <Panel title="Where to go">
        <p>
          Return to the <Link to="/">case list</Link>, open the{' '}
          <Link to="/evidence">evidence explorer</Link>, or check API health in the header.
        </p>
      </Panel>
    </div>
  );
}
