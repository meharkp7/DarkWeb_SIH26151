import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './store/auth';
import { TimeRangeProvider } from './store/TimeRange';
import './styles/tokens.css';
import './styles/base.css';
import './styles/layout.css';
import './styles/components.css';
// Screen-specific layers. Loaded after the shared components so a page can
// refine a primitive without being able to break every other screen.
import './styles/command-center.css';
import './styles/investigations.css';
import './styles/admin.css';
import './styles/search.css';
import './styles/inspector.css';
import './styles/datablock.css';
import './styles/export.css';
// Cross-cutting accessibility rules load last so a component stylesheet cannot
// accidentally win a specificity contest against the focus ring.
import './styles/accessibility.css';

const container = document.getElementById('root');
if (container === null) {
  throw new Error('Root container #root is missing from index.html');
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        {/* Outside the session gate on purpose: the window is a reading
            preference, so it survives a sign-out and a sign-in rather than
            resetting on every expired session. */}
        <TimeRangeProvider>
          <App />
        </TimeRangeProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
