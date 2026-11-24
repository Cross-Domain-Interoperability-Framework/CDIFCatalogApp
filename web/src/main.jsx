import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import App, { OPENING_COPY } from './App.jsx';
import { Harvest, Home, Records } from './pages.jsx';

// Which page shows is the part of the address after "#": "#/new" is the form, "#/records" the
// list, and nothing at all the landing page. The server serves one file whatever follows.
const PAGES = {
  '': <Home />,
  new: <App />,
  records: <Records />,
  search: <Records searching />,
  harvest: <Harvest />,
};

// A record page's "open a copy in the form" link arrives with no "#", and means the form.
if (OPENING_COPY && !window.location.hash) window.history.replaceState(null, '', '#/new');

const pageNow = () => window.location.hash.replace(/^#\/?/, '').split(/[/?]/)[0];

function Root() {
  const [page, setPage] = useState(pageNow);
  useEffect(() => {
    const follow = () => setPage(pageNow());
    window.addEventListener('hashchange', follow);
    return () => window.removeEventListener('hashchange', follow);
  }, []);
  // The key gives each page a fresh start, so the search page does not open on the list's results.
  return <div key={page}>{PAGES[page] ?? <Home />}</div>;
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
