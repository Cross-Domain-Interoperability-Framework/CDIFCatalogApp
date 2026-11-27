// Custom JSON Forms controls for people and organisations. Each is registered against the part of
// the CoreDiscovery form it replaces; everything else keeps the stock Material renderer.
import { Actions, and, rankWith, schemaMatches, scopeEndsWith, uiTypeIs } from '@jsonforms/core';
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
import { InformationType, Keywords, TextList } from './lists.jsx';
import Language from './Language.jsx';
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
    'schema:affiliation': type === PERSON ? { '@type': ORGANISATION, 'schema:name': option.affiliations?.[0] } : undefined,
  });
}

// One author or contributor on one line: name, kind, and for a contributor the role. The
// identifier and affiliation sit behind "More", closed until asked for, as in the ADA metadata
// form. The button counts what is filled in there, so a picked ORCID iD is not forgotten.
function PartyRow({ entry, index, count, ordered, withRole, onChange, onMove, onRemove, idBase }) {
  const [more, setMore] = useState(false);
  const set = (key, value) => onChange(clean({ ...entry, [key]: value }));
  const identifier = entry['schema:identifier'] || '';
  const isOrg = entry['@type'] === ORGANISATION;
  const affiliation = entry['schema:affiliation']?.['schema:name'];
  const hidden = [identifier, !isOrg && affiliation].filter(Boolean).length;
  return (
    <Paper variant="outlined" sx={{ px: 1, py: 0.5 }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'flex-start' } }}>
        {ordered && (
          <Typography variant="body2" color="text.secondary" sx={{ minWidth: 20, pt: 1.75 }}>
            {index + 1}.
          </Typography>
        )}
        <TextField
          id={`${idBase}-name`}
          label={isOrg ? 'Organisation name' : 'Name'}
          fullWidth
          required
          value={entry['schema:name'] || ''}
          error={!entry['schema:name']}
          onChange={(e) => set('schema:name', e.target.value)}
        />
        <TextField
          id={`${idBase}-type`}
          label="Type"
          select
          sx={{ minWidth: 140 }}
          value={entry['@type'] || PERSON}
          onChange={(e) => set('@type', e.target.value)}
        >
          <MenuItem value={PERSON}>Person</MenuItem>
          <MenuItem value={ORGANISATION}>Organisation</MenuItem>
        </TextField>
        {withRole && (
          <TextField
            id={`${idBase}-role`}
            label="Role"
            fullWidth
            required
            error={!entry['schema:roleName']}
            placeholder="For example: editor"
            value={entry['schema:roleName'] || ''}
            onChange={(e) => set('schema:roleName', e.target.value)}
          />
        )}
        <Box sx={{ whiteSpace: 'nowrap', pt: 1 }}>
          <Button
            id={`${idBase}-more`}
            variant="outlined"
            color="inherit"
            aria-expanded={more}
            onClick={() => setMore(!more)}
            sx={{ mr: 0.5 }}
          >
            {more ? 'Less' : hidden ? `More (${hidden})` : 'More'}
          </Button>
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
      {more && (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ pl: ordered ? 3.5 : 0, pt: 0.75, pb: 0.5, '& .MuiFormControl-root': { mt: 0 } }}>
          <TextField
            id={`${idBase}-identifier`}
            label={isOrg ? 'ROR or other identifier' : 'ORCID or other identifier'}
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
              value={affiliation}
              onChange={(name) => set('schema:affiliation', { '@type': ORGANISATION, 'schema:name': name })}
            />
          )}
        </Stack>
      )}
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

// The kind of identifier a number is ("award number"). The schema takes it as text or as a
// reference to a registry by its address, and the stock control shows that choice as two tabs
// with made-up names. One text box does for both: text is saved as text, and an address typed
// here is still text the schema accepts. A reference already in a copied record shows as its
// address.
function IdentifierKind({ data, handleChange, path, label, description, enabled, visible }) {
  if (visible === false) return null;
  const text = typeof data === 'string' ? data : data?.['@id'] || '';
  return (
    <TextField
      label={label}
      helperText={description}
      fullWidth
      disabled={enabled === false}
      value={text}
      onChange={(e) => handleChange(path, e.target.value || undefined)}
      sx={{ my: 1 }}
    />
  );
}

// A distribution is a file to download or a web API. The schema holds the choice as a list of type
// markers; the form holds it as one word (the server lists it again on save), shown here as a
// plain two-option menu. A record copied in may hold the list form, so read the first of it.
const DOWNLOAD = 'schema:DataDownload';
const WEB_API = 'schema:WebAPI';

function DistributionKind({ data, handleChange, path, label, description, visible }) {
  if (visible === false) return null;
  const current = Array.isArray(data) ? data[0] : data;
  return (
    <TextField
      label={label || 'Kind'}
      helperText={description}
      select
      fullWidth
      value={current === WEB_API ? WEB_API : DOWNLOAD}
      onChange={(e) => handleChange(path, e.target.value)}
      sx={{ my: 1 }}
    >
      <MenuItem value={DOWNLOAD}>A file to download</MenuItem>
      <MenuItem value={WEB_API}>A web API or service</MenuItem>
    </TextField>
  );
}

// A web service's endpoint. The schema wants at least one action, each with a name and a target
// giving the address to call (an EntryPoint with a URL template). Most services need only the one,
// so two boxes do: an operation name and the address. The type markers and the EntryPoint wrapper
// are built here; the server lists the markers on save.
function ServiceEndpoint({ data, handleChange, path, label, description, visible }) {
  if (visible === false) return null;
  const action = Array.isArray(data) ? data[0] : undefined;
  const name = action?.['schema:name'] || '';
  const url = action?.['schema:target']?.['schema:urlTemplate'] || '';
  const write = (nextName, nextUrl) => {
    if (!nextName && !nextUrl) return handleChange(path, undefined);
    handleChange(path, [clean({
      '@type': 'schema:Action',
      'schema:name': nextName,
      'schema:target': clean({ '@type': 'schema:EntryPoint', 'schema:urlTemplate': nextUrl }),
    })]);
  };
  return (
    <Box sx={{ my: 1 }}>
      {label && <Typography variant="caption" color="text.secondary">{label}</Typography>}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
        <TextField label="Operation name" sx={{ minWidth: 180 }} value={name} onChange={(e) => write(e.target.value, url)} />
        <TextField label="Endpoint address" fullWidth value={url} onChange={(e) => write(name, e.target.value)} helperText={description} />
      </Stack>
    </Box>
  );
}

export const customRenderers = [
  {
    tester: rankWith(10, schemaMatches((s) => Array.isArray(s.enum) && s.enum.includes(WEB_API))),
    renderer: withJsonFormsControlProps(DistributionKind),
  },
  {
    tester: rankWith(10, scopeEndsWith('#/properties/schema:potentialAction')),
    renderer: withJsonFormsControlProps(ServiceEndpoint),
  },
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
  { tester: rankWith(10, scopeEndsWith('#/properties/schema:inLanguage')), renderer: withJsonFormsControlProps(Language) },
  {
    tester: rankWith(10, scopeEndsWith('#/properties/schema:additionalType')),
    renderer: withJsonFormsControlProps(InformationType),
  },
  { tester: rankWith(10, scopeEndsWith('#/properties/schema:keywords')), renderer: withJsonFormsControlProps(Keywords) },
  {
    tester: rankWith(10, and(scopeEndsWith('#/properties/schema:propertyID'), schemaMatches((s) => !!s.anyOf?.some((b) => b.type === 'string')))),
    renderer: withJsonFormsControlProps(IdentifierKind),
  },
  // Every other list of plain text, wherever it is in the form.
  {
    tester: rankWith(9, and(uiTypeIs('Control'), schemaMatches((s) => s.type === 'array' && s.items?.type === 'string'))),
    renderer: withJsonFormsControlProps(TextList),
  },
];
