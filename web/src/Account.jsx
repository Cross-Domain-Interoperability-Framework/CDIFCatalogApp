// Who is signed in, with the way in and out. Signing in happens at ORCID: the link below sends
// the browser there and ORCID sends it back, so there is no sign-in form here.
import { useEffect, useState } from 'react';
import { Button, Stack, Typography } from '@mui/material';

export default function Account() {
  const [me, setMe] = useState(null);

  useEffect(() => {
    fetch('/api/auth/me')
      .then((res) => (res.ok ? res.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  async function signOut() {
    await fetch('/api/auth/logout', { method: 'POST' });
    setMe({ ...me, signed_in: false });
  }

  // Nothing to show until the server answers, or when it has no ORCID client to sign in with.
  if (!me || (!me.signed_in && !me.configured)) return null;
  if (!me.signed_in) {
    // The server says where sign-in must start: the address ORCID will send the person back to.
    return <Button href={me.sign_in_url} size="small" data-testid="sign-in">Sign in with ORCID</Button>;
  }
  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }} data-testid="account">
      <Typography variant="body2">
        Signed in as {me.name || me.orcid}
        {me.groups.includes('admins') && ' (admin)'}
      </Typography>
      <Button size="small" onClick={signOut}>Sign out</Button>
    </Stack>
  );
}
