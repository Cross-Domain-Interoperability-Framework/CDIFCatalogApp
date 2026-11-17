import { useEffect, useState } from 'react';
import { JsonForms } from '@jsonforms/react';
import { materialCells, materialRenderers } from '@jsonforms/material-renderers';
import { Alert, Box, Container, CssBaseline, Typography } from '@mui/material';

const PROFILE = 'CoreDiscovery';

async function loadJson(name) {
  const res = await fetch(`/forms/${PROFILE}/${name}.json`);
  if (!res.ok) throw new Error(`${name}.json: HTTP ${res.status}`);
  return res.json();
}

export default function App() {
  const [form, setForm] = useState(null);
  const [data, setData] = useState(null);
  const [errors, setErrors] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [server, setServer] = useState('checking');

  useEffect(() => {
    Promise.all(['schema', 'uischema', 'defaults'].map(loadJson))
      .then(([schema, uischema, defaults]) => {
        setForm({ schema, uischema });
        setData(defaults);
      })
      .catch((e) => setLoadError(String(e)));
    fetch('/api/health')
      .then((r) => r.json())
      .then((h) => setServer(`server ${h.status}, database ${h.database}`))
      .catch(() => setServer('server not reachable'));
  }, []);

  if (loadError) return <Alert severity="error">Could not load the form: {loadError}</Alert>;
  if (!form) return <Typography sx={{ m: 2 }}>Loading form...</Typography>;

  return (
    <Container maxWidth="md" sx={{ py: 3 }}>
      <CssBaseline />
      <Typography variant="h5" component="h1">Submit a dataset record</Typography>
      <Typography variant="body2" color="text.secondary" data-testid="server-status">
        Profile: {PROFILE} | {server}
      </Typography>
      <Box sx={{ my: 2 }}>
        <JsonForms
          schema={form.schema}
          uischema={form.uischema}
          data={data}
          renderers={materialRenderers}
          cells={materialCells}
          onChange={({ data: d, errors: e }) => {
            setData(d);
            setErrors(e || []);
          }}
        />
      </Box>
      <Alert severity={errors.length ? 'warning' : 'success'} data-testid="form-errors">
        The form reports {errors.length} problem{errors.length === 1 ? '' : 's'}. This is only the
        check built into the form; the server decides whether a record is valid.
      </Alert>
      <details>
        <summary>Record as it would be saved</summary>
        <pre data-testid="record-json" style={{ overflowX: 'auto', fontSize: 12 }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </Container>
  );
}
