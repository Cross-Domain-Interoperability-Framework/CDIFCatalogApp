// Search boxes backed by the server's /api/lookup endpoints (ORCID for people, ROR for organisations).
import { useEffect, useRef, useState } from 'react';
import { Autocomplete, Box, TextField, Typography } from '@mui/material';

const SEARCH_DELAY_MS = 350;

export async function lookup(kind, params) {
  const res = await fetch(`/api/lookup/${kind}?${new URLSearchParams(params)}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

// Results for `text`, fetched after the typing pauses. A slow answer to an older search is dropped.
function useSearch(kind, text) {
  const [state, setState] = useState({ options: [], loading: false, error: null });
  const latest = useRef(0);
  useEffect(() => {
    const q = text.trim();
    if (q.length < 2) {
      setState({ options: [], loading: false, error: null });
      return undefined;
    }
    const ticket = ++latest.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    const timer = setTimeout(() => {
      lookup(kind, { q })
        .then((options) => ticket === latest.current && setState({ options, loading: false, error: null }))
        .catch((e) => ticket === latest.current && setState({ options: [], loading: false, error: e.message }));
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [kind, text]);
  return state;
}

const describe = (o) => o.affiliations?.slice(0, 2).join('; ') || [o.acronym, o.country].filter(Boolean).join(', ');

function Option({ props, option }) {
  const { key, ...rest } = props;
  return (
    <Box component="li" key={key} {...rest} sx={{ display: 'block !important' }}>
      <Typography variant="body2">{option.name}</Typography>
      <Typography variant="caption" color="text.secondary">
        {[describe(option), option.identifier].filter(Boolean).join(' · ')}
      </Typography>
    </Box>
  );
}

const noOptionsText = (text, error) =>
  error || (text.trim().length < 2 ? 'Type at least two letters' : 'No matches. You can still type it in by hand.');

// A search box that hands the chosen person or organisation to onPick and then empties itself.
export function RegistrySearch({ kind, label, onPick, id }) {
  const [text, setText] = useState('');
  const { options, loading, error } = useSearch(kind, text);
  return (
    <Autocomplete
      id={id}
      fullWidth
      size="small"
      options={options}
      loading={loading}
      value={null}
      inputValue={text}
      blurOnSelect
      filterOptions={(x) => x}
      getOptionLabel={(o) => o.name}
      isOptionEqualToValue={(a, b) => a.identifier === b.identifier}
      noOptionsText={noOptionsText(text, error)}
      onInputChange={(_, v, reason) => reason !== 'reset' && setText(v)}
      onChange={(_, option) => {
        if (option) {
          onPick(option);
          setText('');
        }
      }}
      renderOption={(props, option) => <Option key={option.identifier} props={props} option={option} />}
      renderInput={(params) => <TextField {...params} label={label} />}
    />
  );
}

// A text field for an organisation's name that suggests matches from ROR. Typing a name that is
// not in ROR is allowed. onChange gets the name, plus the ROR entry when one was picked.
export function OrganisationField({ value, onChange, label, id, required, error }) {
  const text = value || '';
  const [focused, setFocused] = useState(false);
  const { options, loading, error: searchError } = useSearch('organisations', focused ? text : '');
  return (
    <Autocomplete
      id={id}
      fullWidth
      freeSolo
      size="small"
      options={options}
      loading={loading}
      inputValue={text}
      filterOptions={(x) => x}
      getOptionLabel={(o) => (typeof o === 'string' ? o : o.name)}
      noOptionsText={noOptionsText(text, searchError)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onInputChange={(_, v, reason) => reason === 'input' && onChange(v, null)}
      onChange={(_, option) => {
        if (option && typeof option !== 'string') onChange(option.name, option);
        else if (option === null) onChange('', null);
      }}
      renderOption={(props, option) => <Option key={option.identifier} props={props} option={option} />}
      renderInput={(params) => (
        <TextField {...params} label={label} required={required} error={!!error} helperText={error || undefined} />
      )}
    />
  );
}
