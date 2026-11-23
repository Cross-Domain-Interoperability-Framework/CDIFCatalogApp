// "Start from a DOI": asks the server what DataCite or Crossref knows and fills empty fields only.
import { useState } from 'react';
import { Alert, Button, Paper, Stack, TextField, Typography } from '@mui/material';
import { lookup } from './lookup.jsx';

const LABELS = {
  'schema:name': 'title',
  'schema:description': 'description',
  'schema:identifier': 'identifier',
  'schema:url': 'landing page',
  'schema:datePublished': 'date published',
  'schema:dateModified': 'date modified',
  'schema:version': 'version',
  'schema:inLanguage': 'language',
  'schema:keywords': 'keywords',
  'schema:license': 'licence',
  'schema:publisher': 'publisher',
  'schema:creator': 'authors',
};

// Empty means the author has not put anything there: no value, blank text, an empty list, or an
// object holding only empty things (the blank form starts with several of those).
export function isEmpty(v) {
  if (v == null || v === '') return true;
  if (Array.isArray(v)) return v.every(isEmpty);
  if (typeof v === 'object') return Object.entries(v).every(([k, x]) => k === '@type' || isEmpty(x));
  return false;
}

// Fill only what is empty, or still holds the value a new record starts with (the language).
// Returns the new record and which fields were filled or left alone.
export function mergeIntoEmpty(data, found, defaults = {}) {
  const next = { ...data };
  const filled = [];
  const kept = [];
  for (const [key, value] of Object.entries(found)) {
    if (isEmpty(data[key]) || data[key] === defaults[key]) {
      next[key] = value;
      filled.push(LABELS[key] || key);
    } else {
      kept.push(LABELS[key] || key);
    }
  }
  return { next, filled, kept };
}

export default function DoiPrefill({ data, defaults, onFill }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  async function run(e) {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const { source, record } = await lookup('doi', { doi: text });
      const { next, filled, kept } = mergeIntoEmpty(data, record, defaults);
      if (filled.length) onFill(next);
      setResult({ severity: filled.length ? 'success' : 'info', source, filled, kept });
    } catch (err) {
      setResult({ severity: 'error', message: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, my: 2 }}>
      <Typography variant="subtitle1" component="h2">Start from a DOI</Typography>
      <Typography variant="body2" color="text.secondary">
        If the dataset already has a DOI, paste it and the form fills in what is registered for it.
        Nothing you have already entered is changed.
      </Typography>
      <Stack component="form" onSubmit={run} direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mt: 1.5 }}>
        <TextField
          id="doi-prefill"
          label="DOI"
          placeholder="10.1234/abcd or https://doi.org/10.1234/abcd"
          size="small"
          fullWidth
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Button type="submit" variant="contained" disabled={busy || text.trim().length < 6} sx={{ whiteSpace: 'nowrap' }}>
          {busy ? 'Looking up...' : 'Fill from DOI'}
        </Button>
      </Stack>
      {result && (
        <Alert severity={result.severity} sx={{ mt: 1.5 }} data-testid="doi-result">
          {result.message}
          {result.filled?.length > 0 && `Filled from ${result.source}: ${result.filled.join(', ')}. `}
          {result.filled?.length === 0 && `${result.source} has a record, but every field it offers is already filled in. `}
          {result.kept?.length > 0 && result.filled?.length > 0 && `Left as you had it: ${result.kept.join(', ')}. `}
          {result.filled?.length > 0 && 'Check each one; registries are sometimes out of date.'}
        </Alert>
      )}
    </Paper>
  );
}
