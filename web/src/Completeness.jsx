// How much of the form has been filled in, overall and tab by tab. It counts fields, and says
// nothing about whether the record can be submitted: only the server's check decides that.
import { Box, LinearProgress, Stack, Typography } from '@mui/material';
import { isEmpty } from './DoiPrefill.jsx';

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// A field counts once the author has put something in it. A group or list still as the blank
// form made it (the catalog entry starts with parts the server writes) does not count.
export function filledBy(data, defaults, fields) {
  const tabs = [];
  for (const [property, field] of Object.entries(fields)) {
    const value = data?.[property];
    const filled = !isEmpty(value) && !(typeof value === 'object' && same(value, defaults?.[property]));
    const tab = tabs[field.tabIndex] || (tabs[field.tabIndex] = { label: field.tab, filled: 0, total: 0 });
    tab.total += 1;
    if (filled) tab.filled += 1;
  }
  return tabs.filter(Boolean);
}

export default function Completeness({ data, defaults, fields }) {
  const tabs = filledBy(data, defaults, fields);
  const filled = tabs.reduce((n, t) => n + t.filled, 0);
  const total = tabs.reduce((n, t) => n + t.total, 0);
  if (!total) return null;
  return (
    <Box sx={{ my: 2 }} data-testid="completeness">
      <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
        <Typography variant="body2" sx={{ whiteSpace: 'nowrap' }}>
          {filled} of {total} fields filled in
        </Typography>
        <LinearProgress
          variant="determinate"
          value={(100 * filled) / total}
          aria-label="Fields filled in"
          sx={{ flex: 1, height: 6, borderRadius: 3 }}
        />
      </Stack>
      <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 0.5 }}>
        {tabs.map((t) => `${t.label}: ${t.filled} of ${t.total}`).join(' · ')}
        . You do not have to fill in every field; the more you give, the easier the data are to find and use.
      </Typography>
    </Box>
  );
}
