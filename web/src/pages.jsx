// The pages around the form: the landing page, the list of records (which is also the search),
// and the harvest page. Which one shows is decided by the part of the address after "#", so the
// server only ever serves one file. The form itself is App.jsx.
import { useEffect, useRef, useState } from 'react';
import {
  Alert, Box, Button, Card, CardActions, CardContent, Chip, Container, CssBaseline, Dialog, DialogActions,
  DialogContent, DialogTitle, Divider, Link, MenuItem, Paper, Stack,
  TextField, ThemeProvider, Typography,
} from '@mui/material';
import AddCircleOutline from '@mui/icons-material/AddCircleOutline';
import CloudDownloadOutlined from '@mui/icons-material/CloudDownloadOutlined';
import ListAlt from '@mui/icons-material/ListAlt';
import Search from '@mui/icons-material/Search';
import Account from './Account.jsx';
import { MapFilter } from './MapFilter.jsx';
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
export function Page({ title, children, maxWidth = 'md' }) {
  return (
    <ThemeProvider theme={theme}>
      <Container maxWidth={maxWidth} sx={{ py: 2 }}>
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

// The facets the search offers, in the plain words shown beside each row of choices.
const FACET_LABELS = { source: 'Source', publisher: 'Published by', profile: 'Detail', keyword: 'Keyword', kind: 'Kind' };

export function Records({ searching }) {
  const [text, setText] = useState('');
  const [sort, setSort] = useState('relevance');
  const [query, setQuery] = useState({ q: '', page: 1, sort: 'relevance', source: '', publisher: '', profile: '', keyword: '', kind: '', start: '', end: '', bbox: '' });
  const [found, setFound] = useState(null);
  const [error, setError] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);

  useEffect(() => {
    let current = true;
    const params = new URLSearchParams({ page: query.page, sort: query.sort, ...(query.q ? { q: query.q } : {}) });
    Object.keys(FACET_LABELS).forEach((k) => { if (query[k]) params.set(k, query[k]); });
    ['start', 'end', 'bbox'].forEach((k) => { if (query[k]) params.set(k, query[k]); });
    api('GET', `/api/records?${params}`)
      .then((answer) => current && (setFound(answer), setError(null)))
      .catch((e) => current && setError(e.message));
    return () => { current = false; };
  }, [query]);

  const search = (e) => {
    e.preventDefault();
    setQuery((prev) => ({ ...prev, q: text.trim(), page: 1 }));
  };

  const toggleFacet = (name, value) =>
    setQuery((prev) => ({ ...prev, [name]: prev[name] === value ? '' : value, page: 1 }));

  const setDate = (which, value) => setQuery((prev) => ({ ...prev, [which]: value, page: 1 }));

  const reorder = (value) => {
    setSort(value);
    setQuery((prev) => ({ ...prev, sort: value, page: 1 }));
  };

  const clearDates = () => setQuery((prev) => ({ ...prev, start: '', end: '', page: 1 }));
  const clearArea = () => setQuery((prev) => ({ ...prev, bbox: '', page: 1 }));

  // the filters now in force, each with the words to show and the way to drop it
  const applied = [
    ...Object.keys(FACET_LABELS).filter((k) => query[k]).map((k) => {
      const chosen = (found?.facets?.[k] || []).find((v) => v.value === query[k]);
      return { key: k, label: `${FACET_LABELS[k]}: ${chosen ? chosen.label : query[k]}`, onDelete: () => toggleFacet(k, query[k]) };
    }),
    ...((query.start || query.end) ? [{
      key: 'dates', label: `Covering ${query.start || '…'} to ${query.end || '…'}`, onDelete: clearDates,
    }] : []),
    ...(query.bbox ? [{ key: 'bbox', label: 'A drawn area', onDelete: clearArea }] : []),
  ];

  const facetGroup = (name) => {
    const values = (found?.facets?.[name]) || [];
    if (values.length < 2 && !query[name]) return null;
    return (
      <Box key={name}>
        <Typography variant="overline" color="text.secondary">{FACET_LABELS[name]}</Typography>
        <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
          {values.map((v) => (
            <Chip
              key={v.value}
              size="small"
              label={`${v.label} (${v.count})`}
              variant={query[name] === v.value ? 'filled' : 'outlined'}
              color={query[name] === v.value ? 'primary' : 'default'}
              onClick={() => toggleFacet(name, v.value)}
            />
          ))}
        </Stack>
      </Box>
    );
  };

  return (
    <Page title={searching ? 'Search the catalog' : 'Records in the catalog'} maxWidth="lg">
      <Stack component="form" onSubmit={search} direction="row" spacing={1} sx={{ mb: 2 }}>
        <TextField
          label="Words in the title, description or keywords"
          fullWidth
          autoFocus={searching}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Button type="submit" variant="contained">Search</Button>
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={3} alignItems="flex-start">
        <Stack
          spacing={2}
          sx={{ width: { xs: '100%', md: 280 }, flexShrink: 0, position: { md: 'sticky' }, top: { md: 16 } }}
        >
          <Box>
            <Typography variant="overline" color="text.secondary">Data covering</Typography>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <TextField type="date" label="from" size="small" InputLabelProps={{ shrink: true }} value={query.start} onChange={(e) => setDate('start', e.target.value)} fullWidth />
              <TextField type="date" label="to" size="small" InputLabelProps={{ shrink: true }} value={query.end} onChange={(e) => setDate('end', e.target.value)} fullWidth />
            </Stack>
          </Box>
          {found?.facets && Object.keys(FACET_LABELS).map(facetGroup).filter(Boolean).reduce(
            (out, group, i) => out.concat(i ? [<Divider key={`d${i}`} flexItem />, group] : [group]), [],
          )}
        </Stack>
        <Box sx={{ flex: 1, minWidth: 0, width: '100%' }}>
          <MapFilter
            value={query.bbox}
            onChange={(bbox) => setQuery((prev) => ({ ...prev, bbox, page: 1 }))}
            results={found?.records || []}
            highlightId={hoveredId}
          />
          {found && (
            <>
              <Stack direction="row" spacing={1} sx={{ mt: 2, mb: 1, alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
                <Typography variant="body2" color="text.secondary" data-testid="record-count" sx={{ flex: 1 }}>
                  {found.total === 0
                    ? (query.q ? `No record holds "${query.q}".` : 'The catalog holds no published records yet.')
                    : `${found.total} ${found.total === 1 ? 'record' : 'records'}${query.q ? ` holding "${query.q}"` : ''}`}
                </Typography>
                <TextField select label="Order" size="small" value={sort} onChange={(e) => reorder(e.target.value)} sx={{ minWidth: 190 }}>
                  <MenuItem value="relevance">Best match</MenuItem>
                  <MenuItem value="modified">Most recently changed</MenuItem>
                  <MenuItem value="title">Title</MenuItem>
                </TextField>
              </Stack>
              {applied.length > 0 && (
                <Stack direction="row" spacing={0.5} sx={{ mb: 1, flexWrap: 'wrap', rowGap: 0.5, alignItems: 'center' }}>
                  <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>Filters:</Typography>
                  {applied.map((f) => <Chip key={f.key} size="small" label={f.label} onDelete={f.onDelete} />)}
                </Stack>
              )}
              <Stack spacing={1} sx={{ mb: 2 }}>
                {found.records.map((r) => (
                  <Paper
                    key={r.id}
                    variant="outlined"
                    onMouseEnter={() => setHoveredId(r.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    sx={{
                      p: 1.5, transition: 'border-color .1s',
                      borderColor: hoveredId === r.id ? 'warning.main' : undefined,
                    }}
                  >
                    <Link href={`/records/${r.id}`} underline="hover" sx={{ fontWeight: 600 }}>{r.name}</Link>
                    {r.description && r.description !== r.name && (
                      <Typography variant="body2" sx={{ mt: 0.25 }}>
                        {r.description}{r.description.length >= 300 ? '…' : ''}
                      </Typography>
                    )}
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                      {r.bbox ? 'Has a place · ' : ''}Changed in the catalog on {whenOf(r.changed)}
                    </Typography>
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
        </Box>
      </Stack>
    </Page>
  );
}

// ---- harvesting ---------------------------------------------------------------------------------

const OUTCOMES = [
  ['added', 'added'], ['updated', 'updated'], ['not modified', 'not changed at the source'],
  ['deleted', 'withdrawn'], ['errored', 'with errors'], ['waiting', 'still waiting'],
];
const RUNNING = ['new', 'running'];

// A harvested record that did not publish, shown so an admin can see why: the problems found in
// it (or, if it could not be read at all, a note), and the record as it was received. A record
// that became CDIF can be opened in the form to be fixed.
function FailedRecord({ recordId, onClose }) {
  const [rec, setRec] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    api('GET', `/api/harvest/records/${recordId}`).then(setRec).catch((e) => setError(e.message));
  }, [recordId]);
  const findings = rec?.validation?.findings || [];
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Why this record did not publish</DialogTitle>
      <DialogContent dividers>
        {error && <Alert severity="error">{error}</Alert>}
        {rec && (
          <Stack spacing={2}>
            {findings.length > 0 ? (
              <Box>
                <Typography variant="subtitle2" gutterBottom>What needs fixing</Typography>
                <Box component="ul" sx={{ pl: 2.5, my: 0, typography: 'body2' }}>
                  {findings.map((f, i) => (
                    <li key={i}>
                      {f.message}
                      {f.where && <Typography variant="caption" color="text.secondary"> — {f.where}</Typography>}
                    </li>
                  ))}
                </Box>
              </Box>
            ) : (
              <Typography variant="body2" color="text.secondary">
                This record could not be read into the catalog's form. The reason is in the list of
                problems; the record as received is below.
              </Typography>
            )}
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                As received{rec.received_format ? ` (${rec.received_format})` : ''}
              </Typography>
              <Box
                component="pre"
                sx={{ maxHeight: 320, overflow: 'auto', bgcolor: 'action.hover', p: 1, borderRadius: 1,
                  fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', m: 0 }}
              >
                {rec.received || '(nothing was stored)'}
              </Box>
            </Box>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {rec?.cdif && <Button href={`/?copy=${recordId}`}>Open in the form</Button>}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

function Run({ jobId, onDone }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [viewId, setViewId] = useState(null);
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
              <li key={i}>
                {e.identifier ? `${e.identifier}: ` : ''}{e.message}
                {e.record_id && (
                  <Button size="small" sx={{ ml: 0.5, py: 0 }} onClick={() => setViewId(e.record_id)}>View</Button>
                )}
              </li>
            ))}
          </Box>
        </details>
      )}
      {viewId && <FailedRecord recordId={viewId} onClose={() => setViewId(null)} />}
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
        A source is a web folder (an address that answers with a page of links to metadata files), a folder in a
        GitHub repository, a sitemap (the
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
