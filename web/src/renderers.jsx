// Custom JSON Forms controls for people and organisations. Each is registered against the part of
// the CoreDiscovery form it replaces; everything else keeps the stock Material renderer.
import { Actions, rankWith, scopeEndsWith } from '@jsonforms/core';
import { useJsonForms, withJsonFormsControlProps } from '@jsonforms/react';
import {
  Box,
  Button,
  IconButton,
  Link,
  MenuItem,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import ArrowDownward from '@mui/icons-material/ArrowDownward';
import ArrowUpward from '@mui/icons-material/ArrowUpward';
import DeleteOutline from '@mui/icons-material/DeleteOutline';
import { useState } from 'react';
import { OrganisationField, RegistrySearch } from './lookup.jsx';

const PERSON = 'schema:Person';
const ORGANISATION = 'schema:Organization';

// Drop keys whose value was cleared, so an emptied field is absent instead of an empty string.
function clean(entry) {
  const out = {};
  for (const [k, v] of Object.entries(entry)) {
    if (v === '' || v == null) continue;
    if (k === 'schema:affiliation' && !v['schema:name']) continue;
    out[k] = v;
  }
  return out;
}

function fromRegistry(type, option) {
  return clean({
    '@type': type,
    'schema:name': option.name,
    'schema:identifier': option.identifier,
    'schema:affiliation': type === PERSON ? { 'schema:name': option.affiliations?.[0] } : undefined,
  });
}

function PartyRow({ entry, index, count, ordered, withRole, onChange, onMove, onRemove, idBase }) {
  const set = (key, value) => onChange(clean({ ...entry, [key]: value }));
  const identifier = entry['schema:identifier'] || '';
  const isOrg = entry['@type'] === ORGANISATION;
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Stack spacing={1.5}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ alignItems: { sm: 'center' } }}>
          {ordered && (
            <Typography variant="body2" color="text.secondary" sx={{ minWidth: 20 }}>
              {index + 1}.
            </Typography>
          )}
          <TextField
            id={`${idBase}-name`}
            label={isOrg ? 'Organisation name' : 'Name'}
            size="small"
            fullWidth
            required
            value={entry['schema:name'] || ''}
            error={!entry['schema:name']}
            onChange={(e) => set('schema:name', e.target.value)}
          />
          <TextField
            id={`${idBase}-type`}
            label="Type"
            size="small"
            select
            sx={{ minWidth: 150 }}
            value={entry['@type'] || PERSON}
            onChange={(e) => set('@type', e.target.value)}
          >
            <MenuItem value={PERSON}>Person</MenuItem>
            <MenuItem value={ORGANISATION}>Organisation</MenuItem>
          </TextField>
          <Box sx={{ whiteSpace: 'nowrap' }}>
            {ordered && (
              <>
                <IconButton aria-label={`Move ${index + 1} up`} size="small" disabled={index === 0} onClick={() => onMove(-1)}>
                  <ArrowUpward fontSize="small" />
                </IconButton>
                <IconButton aria-label={`Move ${index + 1} down`} size="small" disabled={index === count - 1} onClick={() => onMove(1)}>
                  <ArrowDownward fontSize="small" />
                </IconButton>
              </>
            )}
            <IconButton aria-label={`Remove ${entry['schema:name'] || `entry ${index + 1}`}`} size="small" onClick={onRemove}>
              <DeleteOutline fontSize="small" />
            </IconButton>
          </Box>
        </Stack>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
          <TextField
            id={`${idBase}-identifier`}
            label={isOrg ? 'ROR or other identifier' : 'ORCID or other identifier'}
            size="small"
            fullWidth
            value={identifier}
            onChange={(e) => set('schema:identifier', e.target.value)}
            helperText={
              /^https?:\/\//.test(identifier) ? (
                <Link href={identifier} target="_blank" rel="noreferrer">Check this identifier</Link>
              ) : undefined
            }
          />
          {!isOrg && (
            <OrganisationField
              id={`${idBase}-affiliation`}
              label="Affiliation"
              value={entry['schema:affiliation']?.['schema:name']}
              onChange={(name) => set('schema:affiliation', { 'schema:name': name })}
            />
          )}
          {withRole && (
            <TextField
              id={`${idBase}-role`}
              label="Role"
              size="small"
              fullWidth
              value={entry['schema:roleName'] || ''}
              onChange={(e) => set('schema:roleName', e.target.value)}
            />
          )}
        </Stack>
      </Stack>
    </Paper>
  );
}

// The author list and the contributor list: search a registry, pick, and the entry is filled in.
function PartyList({ data, path, handleChange, label, description, visible, uischema }) {
  const [type, setType] = useState(PERSON);
  if (visible === false) return null;
  const entries = Array.isArray(data) ? data : [];
  const ordered = uischema.scope.endsWith('@list'); // authors are ordered; contributors are not
  const update = (next) => handleChange(path, next);
  const add = (entry) => update([...entries, entry]);
  const idBase = path.replace(/[^A-Za-z0-9]+/g, '-');
  const noun = type === PERSON ? 'person' : 'organisation';

  return (
    <Stack spacing={1.5} sx={{ my: 1 }}>
      <Box>
        <Typography variant="subtitle1" component="h3">{label}</Typography>
        {description && <Typography variant="caption" color="text.secondary">{description}</Typography>}
      </Box>
      {entries.length === 0 && (
        <Typography variant="body2" color="text.secondary">None yet. Search below to add one.</Typography>
      )}
      {entries.map((entry, i) => (
        <PartyRow
          key={i}
          idBase={`${idBase}-${i}`}
          entry={entry}
          index={i}
          count={entries.length}
          ordered={ordered}
          withRole={!ordered}
          onChange={(next) => update(entries.map((e, j) => (j === i ? next : e)))}
          onRemove={() => update(entries.filter((_, j) => j !== i))}
          onMove={(by) => {
            const next = [...entries];
            [next[i], next[i + by]] = [next[i + by], next[i]];
            update(next);
          }}
        />
      ))}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ alignItems: { sm: 'center' } }}>
        <ToggleButtonGroup
          exclusive
          sx={{ flexShrink: 0 }}
          size="small"
          value={type}
          onChange={(_, v) => v && setType(v)}
          aria-label="Add a person or an organisation"
        >
          <ToggleButton value={PERSON}>Person</ToggleButton>
          <ToggleButton value={ORGANISATION}>Organisation</ToggleButton>
        </ToggleButtonGroup>
        <Box sx={{ flex: 1, minWidth: 0 }}>
        <RegistrySearch
          key={type}
          id={`${idBase}-search`}
          kind={type === PERSON ? 'people' : 'organisations'}
          label={type === PERSON ? 'Find a person by name or ORCID iD' : 'Find an organisation by name'}
          onPick={(option) => add(fromRegistry(type, option))}
        />
        </Box>
        <Button size="small" sx={{ whiteSpace: 'nowrap', flexShrink: 0 }} onClick={() => add({ '@type': type })}>
          Add {noun} by hand
        </Button>
      </Stack>
    </Stack>
  );
}

// A single organisation's name (publisher, funder). Picking from ROR also fills the identifier
// next to it, when the form has a place for one.
function organisationName(withIdentifier) {
  return function OrganisationName({ data, path, label, required, errors, visible }) {
    const { dispatch } = useJsonForms();
    if (visible === false) return null;
    const parent = path.split('.').slice(0, -1).join('.');
    return (
      <Box sx={{ my: 1 }}>
        <OrganisationField
          id={path.replace(/[^A-Za-z0-9]+/g, '-')}
          label={label}
          required={required}
          error={errors}
          value={data}
          onChange={(name, org) =>
            dispatch(
              Actions.update(parent, (existing) =>
                clean({
                  ...existing,
                  '@type': ORGANISATION,
                  'schema:name': name,
                  // typing a different name by hand must not keep the identifier of the old pick
                  ...(withIdentifier ? { 'schema:identifier': org ? org.identifier : undefined } : {}),
                }),
              ),
            )
          }
        />
      </Box>
    );
  };
}

const PartyListControl = withJsonFormsControlProps(PartyList);

export const customRenderers = [
  { tester: rankWith(10, scopeEndsWith('schema:creator/properties/@list')), renderer: PartyListControl },
  { tester: rankWith(10, scopeEndsWith('#/properties/schema:contributor')), renderer: PartyListControl },
  {
    tester: rankWith(10, scopeEndsWith('schema:publisher/properties/schema:name')),
    renderer: withJsonFormsControlProps(organisationName(true)),
  },
  {
    tester: rankWith(10, scopeEndsWith('schema:funder/properties/schema:name')),
    renderer: withJsonFormsControlProps(organisationName(false)),
  },
];
