import { useEffect, useMemo, useRef, useState } from 'react';
import { JsonForms } from '@jsonforms/react';
import { materialCells, materialRenderers } from '@jsonforms/material-renderers';
import { Alert, Box, Button, Container, CssBaseline, Stack, Typography } from '@mui/material';
import Account from './Account.jsx';
import DoiPrefill from './DoiPrefill.jsx';
import Drafts from './Drafts.jsx';
import { fitRecord } from './fit.js';
import Report, { fieldIndex } from './Report.jsx';
import { customRenderers } from './renderers.jsx';
import { labelOf, translator, withWordingKeys } from './wording.js';

const renderers = [...materialRenderers, ...customRenderers];

const PROFILE = 'CoreDiscovery';
const DRAFT_KEY = `cdif-draft-id:${PROFILE}`;
const SAVE_DELAY_MS = 1500;
const i18n = { locale: 'en-GB', translate: translator(PROFILE) };
// Help text is shown under every field all the time, not only while the field has focus.
const config = { showUnfocusedDescription: true };
const RETRY_DELAY_MS = 5000;

async function loadJson(name) {
  const res = await fetch(`/forms/${PROFILE}/${name}.json`);
  if (!res.ok) throw new Error(`${name}.json: HTTP ${res.status}`);
  return res.json();
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
  return res.json();
}

function storedDraftId() {
  try {
    return localStorage.getItem(DRAFT_KEY);
  } catch {
    return null;
  }
}

function rememberDraftId(id) {
  try {
    if (id) localStorage.setItem(DRAFT_KEY, id);
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* the draft still saves; it just will not be found again after a reload */
  }
}

// A record page links here with ?copy=<record id> to open a copy of that record in the form.
// The id is taken out of the address at once, so a reload opens the saved copy, not a fresh one.
function takeCopyId() {
  const url = new URL(window.location.href);
  const id = url.searchParams.get('copy');
  if (id) {
    url.searchParams.delete('copy');
    window.history.replaceState(null, '', url);
  }
  return id;
}

const REPLACE_DRAFT = 'You have a record in progress in this browser. Opening this copy starts a new '
  + 'record, and the one in progress will no longer open here. Open the copy?';

// Decided once when the page loads, because the form's start-up runs twice in development.
const COPY_ID = (() => {
  const id = takeCopyId();
  return id && (!storedDraftId() || window.confirm(REPLACE_DRAFT)) ? id : null;
})();

const timeOf = (iso) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export default function App() {
  const [form, setForm] = useState(null);
  const [data, setData] = useState(null);
  const [report, setReport] = useState(null); // the server's last validation report
  const [checkedText, setCheckedText] = useState(null); // the record that report was made for
  const [submitted, setSubmitted] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [saveState, setSaveState] = useState({ kind: 'new' });
  const [formKey, setFormKey] = useState(0);
  const [openId, setOpenId] = useState(null); // the draft on screen, for the list of the person's records
  const [copied, setCopied] = useState(null); // { name } of the record this draft began as, or { failed }

  const draftId = useRef(null);
  const savedText = useRef(null); // the document as last loaded or saved, as JSON text
  const latest = useRef(null); // the newest document the form has produced
  const saving = useRef(false);
  const failed = useRef(false); // the last save attempt failed and is being retried
  const timer = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [schema, uischema, defaults] = await Promise.all(
        ['schema', 'uischema', 'defaults'].map(loadJson),
      );
      let document = defaults;
      let state = { kind: 'new' };
      const id = storedDraftId();
      let copy = null;
      if (COPY_ID) {
        const res = await fetch(`/records/${encodeURIComponent(COPY_ID)}?format=cdif`);
        if (res.ok) {
          copy = fitRecord(await res.json(), schema);
        } else if (!cancelled) {
          setCopied({ failed: true });
        }
      }
      if (copy) {
        document = copy;
      } else if (id) {
        try {
          const draft = await api('GET', `/api/drafts/${id}`);
          document = draft.document;
          draftId.current = draft.id;
          setOpenId(draft.id);
          state = { kind: 'saved', at: draft.updated_at, submitted: draft.status === 'submitted' };
        } catch (e) {
          // 404: the draft is gone, start fresh. Anything else: keep the id and say so.
          if (e.status === 404) rememberDraftId(null);
          else state = { kind: 'error', message: 'Could not load your saved draft.' };
        }
      }
      if (cancelled) return;
      // A copy is not saved yet: leave it looking unsaved, so it is saved as a new record at once.
      savedText.current = copy ? null : JSON.stringify(document);
      if (copy) {
        latest.current = copy;
        setCopied({ name: typeof copy['schema:name'] === 'string' ? copy['schema:name'] : '' });
        timer.current = setTimeout(save, 0);
      }
      setForm({ schema, uischema: withWordingKeys(uischema), defaults });
      setData(document);
      setSaveState(state);
      setSubmitted(!!state.submitted);
    })().catch((e) => !cancelled && setLoadError(String(e)));
    return () => {
      cancelled = true;
      clearTimeout(timer.current);
    };
  }, []);

  async function save() {
    if (saving.current) return; // the save in flight reschedules itself if the form moved on
    const document = latest.current;
    const text = JSON.stringify(document);
    if (text === savedText.current) return;
    saving.current = true;
    // While retrying after a failure, leave the failure message up instead of flickering.
    if (!failed.current) setSaveState({ kind: 'saving' });
    try {
      const draft = draftId.current
        ? await api('PUT', `/api/drafts/${draftId.current}`, { document })
        : await api('POST', '/api/drafts', { profile: PROFILE, document });
      draftId.current = draft.id;
      setOpenId(draft.id);
      rememberDraftId(draft.id);
      savedText.current = text;
      failed.current = false;
      setSaveState({ kind: 'saved', at: draft.updated_at });
    } catch {
      failed.current = true;
      setSaveState({ kind: 'error', message: 'Not saved. The server could not be reached. Trying again.' });
    } finally {
      saving.current = false;
      if (JSON.stringify(latest.current) !== savedText.current) {
        schedule(failed.current ? RETRY_DELAY_MS : SAVE_DELAY_MS);
      }
    }
  }

  function schedule(delay = SAVE_DELAY_MS) {
    clearTimeout(timer.current);
    timer.current = setTimeout(save, delay);
  }

  function onChange({ data: d }) {
    setData(d);
    latest.current = d;
    // JSON Forms also calls this when it first renders; only a real change is worth saving.
    if (JSON.stringify(d) !== savedText.current) {
      schedule();
      setSubmitted(false); // the server makes an edited record a draft again
    }
  }

  // A change made outside the form (DOI pre-fill): show it and save it like any other edit.
  function fill(next) {
    setData(next);
    setSubmitted(false);
    latest.current = next;
    schedule();
  }

  function startNew() {
    clearTimeout(timer.current);
    rememberDraftId(null);
    draftId.current = null;
    setOpenId(null);
    failed.current = false;
    savedText.current = JSON.stringify(form.defaults);
    latest.current = form.defaults;
    setData(form.defaults);
    setSaveState({ kind: 'new' });
    setReport(null);
    setSubmitted(false);
    setCopied(null);
    setFormKey((k) => k + 1); // remount so the form drops its own copy of the old record
  }

  // Opening another of the person's records: save this one, then load the page afresh on that one.
  async function open(id) {
    clearTimeout(timer.current);
    await save();
    rememberDraftId(id);
    window.location.reload();
  }

  async function check() {
    const document = latest.current || data;
    const result = await api('POST', '/api/validate', { profile: PROFILE, document, id: draftId.current });
    setReport(result);
    setCheckedText(JSON.stringify(document));
  }

  // Submitting acts on the saved draft, so save first. The server checks the record again itself.
  async function submit() {
    clearTimeout(timer.current);
    await save();
    if (!draftId.current || failed.current) throw new Error('not saved');
    const result = await api('POST', `/api/drafts/${draftId.current}/submit`);
    setReport(result);
    setCheckedText(savedText.current);
    setSubmitted(result.submitted);
  }

  const fields = useMemo(
    () => (form ? fieldIndex(form.uischema, (control) => labelOf(PROFILE, control.i18n)) : {}),
    [form],
  );

  if (loadError) return <Alert severity="error">Could not load the form: {loadError}</Alert>;
  if (!form) return <Typography sx={{ m: 2 }}>Loading form...</Typography>;

  const saveText = {
    new: 'Not saved yet. Your record saves as you type.',
    saving: 'Saving...',
    saved: saveState.at && `Draft saved at ${timeOf(saveState.at)}`,
    error: saveState.message,
  }[saveState.kind];

  return (
    <Container maxWidth="md" sx={{ py: 3 }}>
      <CssBaseline />
      <Stack direction="row" sx={{ justifyContent: 'flex-end', minHeight: 32 }}>
        <Account />
      </Stack>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="h5" component="h1">Submit a dataset record</Typography>
        <Button onClick={startNew} disabled={saveState.kind === 'new'}>Start a new record</Button>
      </Stack>
      <Typography
        variant="body2"
        color={saveState.kind === 'error' ? 'error' : 'text.secondary'}
        role="status"
        data-testid="save-status"
      >
        {saveText}
      </Typography>
      {copied && (copied.failed ? (
        <Alert severity="warning" sx={{ mt: 1 }} onClose={() => setCopied(null)}>
          That record could not be opened. It may have been withdrawn.
        </Alert>
      ) : (
        <Alert severity="info" sx={{ mt: 1 }} onClose={() => setCopied(null)} data-testid="copy-note">
          This is a copy of the catalog record{copied.name ? ` "${copied.name}"` : ''}. It is a new record of your
          own: changing it does not change the record in the catalog. Some details were simplified to fit the
          form, and parts the form has no fields for are kept as they were.
        </Alert>
      ))}
      <Drafts current={openId} onOpen={open} />
      <DoiPrefill data={data} onFill={fill} />
      <Box sx={{ my: 2 }}>
        <JsonForms
          key={formKey}
          schema={form.schema}
          uischema={form.uischema}
          data={data}
          renderers={renderers}
          cells={materialCells}
          i18n={i18n}
          config={config}
          onChange={onChange}
        />
      </Box>
      <Report
        report={report}
        stale={report !== null && JSON.stringify(data) !== checkedText}
        fields={fields}
        submitted={submitted}
        onCheck={check}
        onSubmit={submit}
      />
      <details>
        <summary>Record as it would be saved</summary>
        <pre data-testid="record-json" style={{ overflowX: 'auto', fontSize: 12 }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </Container>
  );
}
