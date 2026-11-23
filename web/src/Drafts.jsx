// The signed-in person's own records, so one begun in another browser, or set aside for a new
// one, can be opened again. The server lists nothing for someone who is not signed in.
import { useEffect, useState } from 'react';
import { Button, Stack, Typography } from '@mui/material';

const whenOf = (iso) => new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

export default function Drafts({ current, onOpen }) {
  const [drafts, setDrafts] = useState([]);

  // Asked again when the open record changes, so a record saved for the first time joins the list.
  useEffect(() => {
    fetch('/api/drafts')
      .then((res) => (res.ok ? res.json() : []))
      .then(setDrafts)
      .catch(() => setDrafts([]));
  }, [current]);

  if (!drafts.some((d) => d.id !== current)) return null;
  return (
    <details data-testid="your-records">
      <summary>Your records ({drafts.length})</summary>
      <Stack spacing={0.5} sx={{ my: 1 }}>
        {drafts.map((d) => (
          <Stack key={d.id} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <Typography variant="body2" sx={{ flexGrow: 1 }}>
              {d.name || 'Untitled record'}
              {' · '}
              {d.status === 'submitted' ? 'submitted' : 'not submitted'}
              {' · saved '}
              {whenOf(d.updated_at)}
            </Typography>
            {d.id === current
              ? <Typography variant="body2" color="text.secondary">Open now</Typography>
              : <Button size="small" onClick={() => onOpen(d.id)}>Open</Button>}
          </Stack>
        ))}
      </Stack>
    </details>
  );
}
