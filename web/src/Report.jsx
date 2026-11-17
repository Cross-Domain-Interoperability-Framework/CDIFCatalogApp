// "Check my record": asks the server whether the record is valid and lists what it found in plain
// words, each finding linked to its field. The server's answer is the only one that counts; the
// form's own checks are not shown.
import { useState } from 'react';
import { Alert, Box, Button, Chip, Link, Paper, Stack, Typography } from '@mui/material';

const GROUPS = [
  { severity: 'violation', title: 'Must be fixed before you can submit', color: 'error' },
  { severity: 'warning', title: 'Recommended', color: 'warning' },
  { severity: 'info', title: 'Worth considering', color: 'info' },
];

// Where each field is in the form: top-level property -> { tab, tabIndex, label, scope }.
// Read from the form's own layout file, so it follows the form when that changes.
export function fieldIndex(uischema) {
  const index = {};
  const tabs = uischema.type === 'Categorization' ? uischema.elements : [];
  const walk = (el, tab, tabIndex) => {
    if (el.scope) {
      const property = el.scope.split('/')[2];
      if (!index[property]) index[property] = { tab, tabIndex, label: el.label || property, scope: el.scope };
    }
    (el.elements || []).forEach((child) => walk(child, tab, tabIndex));
  };
  tabs.forEach((tab, i) => walk(tab, tab.label, i));
  return index;
}

// Open the field's tab and bring the field into view. The tabs belong to JSON Forms, which
// gives no way to switch them from outside, so this clicks the tab the way a person would.
function goTo(field) {
  const tab = document.querySelectorAll('[role="tab"]')[field.tabIndex];
  if (tab) tab.click();
  setTimeout(() => {
    const target =
      document.getElementById(`${field.scope}-input`) ||
      document.querySelector(`[id^="${CSS.escape(field.scope)}"]`) ||
      tab;
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (target.focus) target.focus({ preventScroll: true });
  }, 100);
}

function Finding({ finding, field }) {
  const place = [field?.label, finding.where].filter(Boolean).join(', ');
  // The schema's messages are a predicate ("is missing"); the rules' are whole sentences.
  const predicate = finding.source === 'schema';
  return (
    <Box component="li" sx={{ mb: 0.75 }}>
      {field ? (
        <Link component="button" type="button" onClick={() => goTo(field)} sx={{ fontWeight: 600, verticalAlign: 'baseline' }}>
          {place}
        </Link>
      ) : (
        <Box component="span" sx={{ fontWeight: 600 }}>{place || 'The record'}</Box>
      )}
      {predicate ? ` ${finding.message}.` : `: ${finding.message}`}
      {field && <Typography component="span" variant="caption" color="text.secondary"> ({field.tab} tab)</Typography>}
    </Box>
  );
}

// onCheck and onSubmit ask the server and store its report. `stale` is true when the record has
// changed since `report` was made.
export default function Report({ report, stale, fields, onCheck, onSubmit, submitted }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  async function run(kind, action) {
    setBusy(kind);
    setError(null);
    try {
      await action();
    } catch {
      setError('The server could not be reached. Your record is unchanged; try again.');
    } finally {
      setBusy(null);
    }
  }

  const canSubmit = report?.valid && !stale && !submitted;
  return (
    <Paper variant="outlined" sx={{ p: 2, my: 2 }} data-testid="report">
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ alignItems: { sm: 'center' } }}>
        <Typography variant="subtitle1" component="h2" sx={{ flex: 1 }}>Check and submit</Typography>
        <Button variant="outlined" disabled={!!busy} onClick={() => run('check', onCheck)}>
          {busy === 'check' ? 'Checking...' : report ? 'Check again' : 'Check my record'}
        </Button>
        <Button variant="contained" disabled={!canSubmit || !!busy} onClick={() => run('submit', onSubmit)}>
          {busy === 'submit' ? 'Submitting...' : 'Submit record'}
        </Button>
      </Stack>

      {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
      {submitted && !stale && (
        <Alert severity="success" sx={{ mt: 1.5 }} data-testid="submitted">
          Submitted. If you change anything, the record becomes a draft again until you resubmit.
        </Alert>
      )}
      {!report && !error && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Check the record at any time. It can be submitted once nothing is left that must be fixed.
        </Typography>
      )}

      {report && (
        <Box sx={{ mt: 1.5, opacity: stale ? 0.6 : 1 }}>
          {stale && (
            <Alert severity="info" sx={{ mb: 1.5 }}>
              You have changed the record since this check. Check again to update the list.
            </Alert>
          )}
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1, mb: 1 }} data-testid="report-counts">
            <Chip
              color={report.valid ? 'success' : 'error'}
              label={report.valid ? 'Nothing must be fixed' : `${report.counts.violation} to fix`}
            />
            <Chip variant="outlined" label={`${report.counts.warning} recommended`} />
            <Chip variant="outlined" label={`${report.counts.info} worth considering`} />
          </Stack>
          {GROUPS.map(({ severity, title, color }) => {
            const items = report.findings.filter((f) => f.severity === severity);
            if (!items.length) return null;
            return (
              <Box key={severity} sx={{ mt: 1.5 }}>
                <Typography variant="subtitle2" color={`${color}.main`}>{title}</Typography>
                <Box component="ul" sx={{ pl: 2.5, my: 0.5, typography: 'body2' }}>
                  {items.map((f, i) => <Finding key={i} finding={f} field={fields[f.property]} />)}
                </Box>
              </Box>
            );
          })}
        </Box>
      )}
    </Paper>
  );
}
