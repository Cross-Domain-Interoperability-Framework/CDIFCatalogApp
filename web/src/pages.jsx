// The pages around the form: the landing page, the list of records (which is also the search),
// and the harvest page. Which one shows is decided by the part of the address after "#", so the
// server only ever serves one file. The form itself is App.jsx.
import { useEffect, useRef, useState } from 'react';
import {
  Alert, Box, Button, Card, CardActions, CardContent, Chip, Container, CssBaseline, Link, MenuItem, Paper, Stack,
  TextField, ThemeProvider, Typography,
} from '@mui/material';
import AddCircleOutline from '@mui/icons-material/AddCircleOutline';
import CloudDownloadOutlined from '@mui/icons-material/CloudDownloadOutlined';
import ListAlt from '@mui/icons-material/ListAlt';
import Search from '@mui/icons-material/Search';
import Account from './Account.jsx';
import theme from './theme.js';

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const answer = await res.json().catch(() => null);
  if (!res.ok) throw Object.assign(new Error(answer?.detail || `The server answered ${res.status}.`), { status: res.status });
  return answer;
}

function useMe() {
  const [me, setMe] = useState(null);
  useEffect(() => {
    api('GET', '/api/auth/me').then(setMe).catch(() => setMe({ signed_in: false }));
  }, []);
  return me;
}

const whenOf = (iso) => new Date(iso).toLocaleDateString([], { dateStyle: 'medium' });

// The frame every page but the form shares: the catalog's name, which leads home, and the account.
export function Page({ title, children }) {
  return (
    <ThemeProvider theme={theme}>
      <Container maxWidth="md" sx={{ py: 2 }}>
        <CssBaseline />
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', minHeight: 32 }}>
          <Link href="#/" underline="hover" variant="body2">CDIF Catalog</Link>
          <Account />
        </Stack>
        {title && <Typography variant="h5" component="h1" sx={{ mt: 1, mb: 2 }}>{title}</Typography>}
        {children}
      </Container>
    </ThemeProvider>
  );
}

// ---- the landing page ---------------------------------------------------------------------------

function Choice({ icon, title, text, action, href, disabled, note }) {
  return (
    <Card variant="outlined" sx={{ display: 'flex', flexDirection: 'column', textAlign: 'center' }}>
      <CardContent sx={{ flex: 1 }}>
        <Box sx={{ color: 'primary.main', '& svg': { fontSize: 44 } }}>{icon}</Box>
        <Typography variant="h6" component="h2" sx={{ mt: 1 }}>{title}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{text}</Typography>
      </CardContent>
      <CardActions sx={{ justifyContent: 'center', flexDirection: 'column', pb: 2 }}>
        <Button variant="outlined" href={disabled ? undefined : href} disabled={disabled}>{action}</Button>
        {note && <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>{note}</Typography>}
      </CardActions>
    </Card>
  );
}

export function Home() {
  const me = useMe();
  const mayHarvest = !!me?.permissions?.includes('harvest');
  return (
    <Page>
      <Box sx={{ textAlign: 'center', my: 4 }}>
        <Typography variant="h4" component="h1">CDIF Catalog</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Metadata gathered from many sources and offered in one form.
        </Typography>
      </Box>
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: 'repeat(4, 1fr)' } }}>
        <Choice
          icon={<ListAlt />}
          title="Browse records"
          text="See the records the catalog holds, newest first."
          action="View records"
          href="#/records"
        />
        <Choice
          icon={<AddCircleOutline />}
          title="Create new record"
          text="Describe a dataset in the form, check it and submit it."
          action="New record"
          href="#/new"
        />
        <Choice
          icon={<CloudDownloadOutlined />}
          title="Harvest records"
          text="Gather records from a web folder of metadata files, a site's sitemap, or another catalogue or repository."
          action="Harvest"
          href="#/harvest"
          disabled={!mayHarvest}
          note={mayHarvest ? undefined : me?.signed_in ? 'For administrators.' : 'Sign in as an administrator.'}
        />
        <Choice
          icon={<Search />}
          title="Search catalog"
          text="Find records by words, ranked, with the best match first."
          action="Search"
          href="#/search"
        />
      </Box>
    </Page>
  );
}

// ---- the list of records, and the search --------------------------------------------------------

export function Records({ searching }) {
  const [text, setText] = useState('');
  const [sort, setSort] = useState('relevance');
  const [query, setQuery] = useState({ q: '', page: 1, sort: 'relevance' });
  const [found, setFound] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let current = true;
    const params = new URLSearchParams({ page: query.page, sort: query.sort, ...(query.q ? { q: query.q } : {}) });
    api('GET', `/api/records?${params}`)
      .then((answer) => current && (setFound(answer), setError(null)))
      .catch((e) => current && setError(e.message));
    return () => { current = false; };
  }, [query]);

  const search = (e) => {
    e.preventDefault();
    setQuery({ q: text.trim(), page: 1, sort });
  };

  const reorder = (value) => {
    setSort(value);
    setQuery((prev) => ({ ...prev, sort: value, page: 1 }));
  };

  return (
    <Page title={searching ? 'Search the catalog' : 'Records in the catalog'}>
      <Stack component="form" onSubmit={search} direction="row" spacing={1} sx={{ mb: 2 }}>
        <TextField
          label="Words in the title, description or keywords"
          fullWidth
          autoFocus={searching}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <TextField select label="Order" value={sort} onChange={(e) => reorder(e.target.value)} sx={{ minWidth: 190 }}>
          <MenuItem value="relevance">Best match</MenuItem>
          <MenuItem value="modified">Most recently changed</MenuItem>
          <MenuItem value="title">Title</MenuItem>
        </TextField>
        <Button type="submit" variant="contained">Search</Button>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
      {found && (
        <>
          <Typography variant="body2" color="text.secondary" data-testid="record-count">
            {found.total === 0
              ? (query.q ? `No record holds "${query.q}".` : 'The catalog holds no published records yet.')
              : `${found.total} ${found.total === 1 ? 'record' : 'records'}${query.q ? ` holding "${query.q}"` : ''}`}
          </Typography>
          <Stack spacing={1} sx={{ my: 1 }}>
            {found.records.map((r) => (
              <Paper key={r.id} variant="outlined" sx={{ p: 1.5 }}>
                <Link href={`/records/${r.id}`} underline="hover" sx={{ fontWeight: 600 }}>{r.name}</Link>
                {r.description && r.description !== r.name && (
                  <Typography variant="body2" sx={{ mt: 0.25 }}>
                    {r.description}{r.description.length >= 300 ? '…' : ''}
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary">Changed in the catalog on {whenOf(r.changed)}</Typography>
              </Paper>
            ))}
          </Stack>
          {found.pages > 1 && (
            <Stack direction="row" spacing={2} sx={{ alignItems: 'center', justifyContent: 'center' }}>
              <Button disabled={query.page <= 1} onClick={() => setQuery({ ...query, page: query.page - 1 })}>Previous</Button>
              <Typography variant="body2">Page {found.page} of {found.pages}</Typography>
              <Button disabled={query.page >= found.pages} onClick={() => setQuery({ ...query, page: query.page + 1 })}>Next</Button>
            </Stack>
          )}
        </>
      )}
    </Page>
  );
}

// ---- harvesting ---------------------------------------------------------------------------------

const OUTCOMES = [
  ['added', 'added'], ['updated', 'updated'], ['not modified', 'not changed at the source'],
  ['deleted', 'withdrawn'], ['errored', 'with errors'], ['waiting', 'still waiting'],
];
const RUNNING = ['new', 'running'];

function Run({ jobId, onDone }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const done = useRef(onDone);
  done.current = onDone;

  // Asked again every few seconds until the run ends; the worker does the harvesting.
  useEffect(() => {
    let timer;
    let stopped = false;
    const ask = () => api('GET', `/api/harvest/jobs/${jobId}`)
      .then((answer) => {
        if (stopped) return;
        setJob(answer);
        if (RUNNING.includes(answer.status)) timer = setTimeout(ask, 3000);
        else done.current();
      })
      .catch((e) => !stopped && setError(e.message));
    ask();
    return () => { stopped = true; clearTimeout(timer); };
  }, [jobId]);

  if (error) return <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>;
  if (!job) return null;
  const counts = OUTCOMES.filter(([key]) => job.stats?.[key]).map(([key, words]) => `${job.stats[key]} ${words}`);
  return (
    <Box sx={{ mt: 1 }} data-testid="run">
      <Typography variant="body2">
        {RUNNING.includes(job.status) ? 'Harvesting… ' : `Run ${job.status}. `}
        {counts.join(', ') || (RUNNING.includes(job.status) ? 'Nothing found yet.' : 'Nothing was found.')}
      </Typography>
      {job.errors?.length > 0 && (
        <details>
          <summary>{job.errors.length} {job.errors.length === 1 ? 'problem' : 'problems'}</summary>
          <Box component="ul" sx={{ pl: 2.5, my: 0.5, typography: 'body2' }}>
            {job.errors.map((e, i) => (
              <li key={i}>{e.identifier ? `${e.identifier}: ` : ''}{e.message}</li>
            ))}
          </Box>
        </details>
      )}
    </Box>
  );
}

// The files a person picked, read as text: metadata files are text, and the server takes them so.
const asText = (files) => Promise.all([...files].map(async (f) => ({ name: f.name, content: await f.text() })));

function Source({ id }) {
  const [source, setSource] = useState(null);
  const [error, setError] = useState(null);
  const load = () => api('GET', `/api/harvest/sources/${id}`).then(setSource).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);
  if (!source) return error ? <Alert severity="error">{error}</Alert> : null;

  const latest = source.jobs[0];
  const act = (path) => api('POST', path).then(load).catch((e) => setError(e.message));
  const busy = latest && RUNNING.includes(latest.status);
  const uploaded = source.type === 'upload';
  const addFiles = (e) => {
    const picked = e.target.files;
    if (!picked.length) return;
    asText(picked)
      .then((files) => api('POST', '/api/harvest/uploads', { source: id, files }))
      .then(() => { setError(null); load(); })
      .catch((err) => setError(err.message));
    e.target.value = '';
  };
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }} data-testid="source">
      <Stack direction="row" spacing={2} sx={{ alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography sx={{ fontWeight: 600 }}>{source.title}</Typography>
          {uploaded
            ? <Typography variant="body2" color="text.secondary">Uploaded files</Typography>
            : <Link href={source.url} target="_blank" rel="noreferrer" variant="body2" sx={{ wordBreak: 'break-all' }}>{source.url}</Link>}
          <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: 'wrap', rowGap: 0.5 }}>
            {Object.entries(source.records).map(([status, n]) => (
              <Chip key={status} size="small" variant="outlined" label={`${n} ${status}`} />
            ))}
            {Object.keys(source.records).length === 0 && <Chip size="small" variant="outlined" label="no records yet" />}
          </Stack>
        </Box>
        <Stack direction="row" spacing={1} sx={{ flexShrink: 0 }}>
          {latest && !busy && (
            <Button onClick={() => act(`/api/harvest/jobs/${latest.id}/retry`)} title="Look again at only the records that failed in the last run">
              Retry failed
            </Button>
          )}
          {uploaded ? (
            <Button variant="outlined" component="label" disabled={busy} title="Add files to this batch, or replace ones already in it by name">
              Add files
              <input type="file" multiple hidden onChange={addFiles} />
            </Button>
          ) : (
            <Button variant="outlined" disabled={busy} onClick={() => act(`/api/harvest/sources/${id}/jobs`)}>Harvest now</Button>
          )}
        </Stack>
      </Stack>
      {error && <Alert severity="error" sx={{ mt: 1 }} onClose={() => setError(null)}>{error}</Alert>}
      {latest && <Run key={latest.id} jobId={latest.id} onDone={load} />}
    </Paper>
  );
}

export function Harvest() {
  const me = useMe();
  const [sources, setSources] = useState(null);
  const [types, setTypes] = useState([]);
  const [draft, setDraft] = useState({ title: '', url: '', type: '', only: '' });
  const [error, setError] = useState(null);
  const [batch, setBatch] = useState('');
  const picker = useRef(null);
  const allowed = !!me?.permissions?.includes('harvest');

  const load = () => api('GET', '/api/harvest/sources').then(setSources).catch((e) => setError(e.message));
  useEffect(() => {
    if (!allowed) return;
    load();
    api('GET', '/api/harvest/types').then((list) => {
      setTypes(list);
      setDraft((d) => ({ ...d, type: d.type || list[0]?.type || '' }));
    }).catch((e) => setError(e.message));
  }, [allowed]);

  const add = (e) => {
    e.preventDefault();
    const source = { title: draft.title.trim(), url: draft.url.trim(), type: draft.type };
    // A sitemap lists every page of a site; this keeps the ones that describe datasets.
    if (draft.type === 'sitemap' && draft.only.trim()) source.config = { only: draft.only.trim() };
    api('POST', '/api/harvest/sources', source)
      .then(() => { setDraft({ ...draft, title: '', url: '', only: '' }); setError(null); load(); })
      .catch((err) => setError(err.message));
  };

  const upload = (e) => {
    e.preventDefault();
    asText(picker.current.files)
      .then((files) => api('POST', '/api/harvest/uploads', { title: batch.trim(), files }))
      .then(() => { setBatch(''); picker.current.value = ''; setError(null); load(); })
      .catch((err) => setError(err.message));
  };

  if (!me) return <Page title="Harvest records" />;
  if (!allowed) {
    return (
      <Page title="Harvest records">
        <Alert severity="info">
          {me.signed_in
            ? 'Harvesting is for administrators. Your account is not one.'
            : 'Harvesting is for administrators. Sign in with ORCID, at the top of the page, with an administrator account.'}
        </Alert>
      </Page>
    );
  }
  return (
    <Page title="Harvest records">
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        A source is a web folder (an address that answers with a page of links to metadata files), a sitemap (the
        file a site publishes to list its pages), another catalogue that offers the CSW search interface, a
        repository that offers OAI-PMH, a STAC catalogue, or a DCAT catalogue. The
        catalog fetches each file, page or record, converts what it finds, checks it, and publishes it if it passes.
        Metadata files on your own computer can be uploaded instead, and go through the same steps.
      </Typography>
      <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
        <Typography variant="subtitle1" component="h2">Add a source</Typography>
        <Stack component="form" onSubmit={add} direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'flex-start' } }}>
          <TextField label="Name" required value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} sx={{ flex: 1 }} />
          <TextField label="Web address of the source" required type="url" value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} sx={{ flex: 2 }} />
          {types.length > 1 && (
            <TextField label="Kind" select value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })} sx={{ minWidth: 140 }}>
              {types.map((t) => <MenuItem key={t.type} value={t.type}>{t.title}</MenuItem>)}
            </TextField>
          )}
          {draft.type === 'sitemap' && (
            <TextField
              label="Only addresses holding"
              placeholder="/dataset/"
              value={draft.only}
              onChange={(e) => setDraft({ ...draft, only: e.target.value })}
              sx={{ flex: 1 }}
            />
          )}
          <Button type="submit" variant="contained" sx={{ mt: { sm: '6px !important' } }}>Add</Button>
        </Stack>
      </Paper>
      <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
        <Typography variant="subtitle1" component="h2">Upload files</Typography>
        <Stack component="form" onSubmit={upload} direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
          <TextField label="Name for this batch" required value={batch} onChange={(e) => setBatch(e.target.value)} sx={{ flex: 1 }} />
          <Box sx={{ flex: 2 }}>
            <input ref={picker} type="file" multiple required aria-label="Metadata files" />
          </Box>
          <Button type="submit" variant="contained">Upload</Button>
        </Stack>
      </Paper>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {sources && sources.length === 0 && <Typography variant="body2" color="text.secondary">No sources yet.</Typography>}
      <Stack spacing={1}>
        {(sources || []).map((s) => <Source key={s.id} id={s.id} />)}
      </Stack>
    </Page>
  );
}
