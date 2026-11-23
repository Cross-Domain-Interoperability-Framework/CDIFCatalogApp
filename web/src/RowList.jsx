// A list of groups (grants, licences, variables, downloads) as compact rows. Each entry shows
// its main fields on one line; the rest open from a "More" button, closed until asked for, as in
// the ADA metadata form. It replaces the stock list, where a new entry is a closed panel and an
// open one shows every field.
//
// The fields come from the list's own layout in the form's layout file. Which of them go on the
// row is set below; a list not named there shows its first two.
import { useState } from 'react';
import { and, composePaths, createDefaultValue, rankWith, Resolve, schemaMatches, uiTypeIs } from '@jsonforms/core';
import { JsonFormsDispatch, useJsonForms, withJsonFormsArrayLayoutProps } from '@jsonforms/react';
import { Box, Button, IconButton, Paper, Stack, Typography } from '@mui/material';
import DeleteOutline from '@mui/icons-material/DeleteOutline';
import { isEmpty } from './DoiPrefill.jsx';

const ON_ROW = {
  'schema:funding': ['schema:name', 'schema:funder/schema:name'],
  'schema:license': ['schema:name', 'schema:url'],
  'schema:conditionsOfAccess': ['schema:name', 'schema:url'],
  'schema:relatedLink': ['schema:linkRelationship', 'schema:target/schema:url'],
  'schema:variableMeasured': ['schema:name', 'schema:unitText'],
  'schema:spatialCoverage': ['schema:name', 'schema:geo/schema:box'],
  'schema:distribution': ['schema:name', 'schema:contentUrl'],
};

// "#/properties/schema:funder/properties/schema:name" -> ["schema:funder", "schema:name"]
const steps = (scope) => scope.replace(/^#\/properties\//, '').split('/properties/');

// The controls of a layout, in order. A control's own nested layout stays inside it.
function controlsOf(element) {
  if (!element) return [];
  if (element.type === 'Control') return [element];
  return (element.elements || []).flatMap(controlsOf);
}

function split(uischema) {
  const controls = controlsOf(uischema.options?.detail);
  const wanted = ON_ROW[steps(uischema.scope).pop()];
  const onRow = wanted
    ? wanted.map((w) => controls.find((c) => steps(c.scope).join('/') === w)).filter(Boolean)
    : controls.slice(0, 2);
  return { onRow, behind: controls.filter((c) => !onRow.includes(c)) };
}

function Row({ item, itemPath, schema, onRow, behind, renderers, cells, enabled, onRemove, name }) {
  const [more, setMore] = useState(false);
  const filled = behind.filter((c) => !isEmpty(steps(c.scope).reduce((value, step) => value?.[step], item))).length;
  const show = (elements, type) => (
    <JsonFormsDispatch
      schema={schema}
      uischema={{ type, elements }}
      path={itemPath}
      renderers={renderers}
      cells={cells}
      enabled={enabled}
    />
  );
  return (
    <Paper variant="outlined" sx={{ px: 1, py: 0.5 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>{show(onRow, 'HorizontalLayout')}</Box>
        <Box sx={{ whiteSpace: 'nowrap', pt: 1 }}>
          {behind.length > 0 && (
            <Button variant="outlined" color="inherit" aria-expanded={more} onClick={() => setMore(!more)} sx={{ mr: 0.5 }}>
              {more ? 'Less' : filled ? `More (${filled})` : 'More'}
            </Button>
          )}
          <IconButton aria-label={`Remove ${name}`} size="small" onClick={onRemove}>
            <DeleteOutline fontSize="small" />
          </IconButton>
        </Box>
      </Stack>
      {more && <Box sx={{ pb: 0.5 }}>{show(behind, 'VerticalLayout')}</Box>}
    </Paper>
  );
}

function RowList({ path, schema, rootSchema, uischema, label, description, addItem, removeItems, renderers, cells, enabled, visible }) {
  const { core } = useJsonForms();
  if (visible === false) return null;
  const items = Resolve.data(core.data, path);
  const entries = Array.isArray(items) ? items : [];
  const { onRow, behind } = split(uischema);
  return (
    <Stack spacing={1} sx={{ my: 1 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <Box>
          <Typography variant="subtitle1" component="h3">{label}</Typography>
          {description && <Typography variant="caption" color="text.secondary">{description}</Typography>}
        </Box>
        <Button
          variant="outlined"
          sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}
          aria-label={`Add to ${label}`}
          disabled={enabled === false}
          onClick={addItem(path, createDefaultValue(schema, rootSchema))}
        >
          Add
        </Button>
      </Stack>
      {entries.length === 0 && <Typography variant="body2" color="text.secondary">None yet.</Typography>}
      {entries.map((item, index) => (
        <Row
          // An entry has no identity of its own; its place in the list is all there is.
          key={index}
          item={item}
          itemPath={composePaths(path, `${index}`)}
          schema={schema}
          onRow={onRow}
          behind={behind}
          renderers={renderers}
          cells={cells}
          enabled={enabled}
          name={`entry ${index + 1} of ${label}`}
          onRemove={removeItems(path, [index])}
        />
      ))}
    </Stack>
  );
}

// Any list of groups that the layout gives fields for. The author and contributor lists have
// their own control, registered with a higher rank.
export const rowListRenderer = {
  tester: rankWith(
    9,
    and(
      uiTypeIs('Control'),
      schemaMatches((s) => s.type === 'array' && s.items?.type === 'object'),
      (uischema) => typeof uischema.options?.detail === 'object',
    ),
  ),
  renderer: withJsonFormsArrayLayoutProps(RowList),
};
