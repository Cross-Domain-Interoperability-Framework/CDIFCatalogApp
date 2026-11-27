// Corrections laid over the form files copied from metadataBuildingBlocks, which are not edited
// here. All but one undo a known defect in those files; when a refresh of the files brings the
// fix, delete the correction (docs/form-inventory.md lists the defects and where they are filed).
// Those that are not defects (`withoutKind`, `withDistributionFields`, `correctDefaults`, keywords
// as text or a term) are choices made here and say so.

// The layout addresses what a related link points to as "target"; the schema's property is
// "schema:target". With the wrong name the two fields show nothing that can be filled in.
export function correctLayout(uischema) {
  return withDistributionFields(withoutKind(JSON.parse(
    JSON.stringify(uischema).replaceAll('"#/properties/target/', '"#/properties/schema:target/'),
  )));
}

// A choice made here: the layout gives a distribution no fields of its own, so the stock form
// shows all twenty-odd the schema has, under generated names. We give it a hand-written layout
// instead: a kind (file download or web API), the fields shared by both, and then the fields for
// the kind chosen. The rest (a service's individual operations, a checksum, image sizes) are not
// shown; where a copied record holds them, they are kept.
const DOWNLOAD_FIELDS = ['schema:contentUrl', 'schema:encodingFormat', 'schema:contentSize'];
const WEBAPI_FIELDS = ['schema:serviceType', 'schema:potentialAction', 'schema:termsOfService', 'schema:documentation'];

// Show a field only for the chosen kind. The kind is held as one word (the schema wants a list,
// which the server adds on save), but a record copied in may hold it as a list, so match either.
const forKind = (kind) => ({
  effect: 'SHOW',
  condition: {
    scope: '#/properties/@type',
    schema: { anyOf: [{ const: kind }, { type: 'array', contains: { const: kind } }] },
  },
});
const control = (field, rule) => ({ type: 'Control', scope: `#/properties/${field}`, ...(rule ? { rule } : {}) });

function withDistributionFields(element) {
  if (Array.isArray(element)) return element.map(withDistributionFields);
  if (!element || typeof element !== 'object') return element;
  if (element.type === 'Control' && element.scope === '#/properties/schema:distribution') {
    const detail = {
      type: 'VerticalLayout',
      elements: [
        control('@type'),
        control('schema:name'),
        ...DOWNLOAD_FIELDS.map((field) => control(field, forKind('schema:DataDownload'))),
        ...WEBAPI_FIELDS.map((field) => control(field, forKind('schema:WebAPI'))),
        control('schema:description'),
      ],
    };
    return { ...element, options: { ...element.options, detail } };
  }
  return Object.fromEntries(Object.entries(element).map(([k, v]) => [k, withDistributionFields(v)]));
}

// Not a defect, a choice made here: this form describes datasets only, so the field asking what
// kind of thing the record describes is taken out. Every record keeps the "dataset" marker the
// form starts with. The same address inside a list's own layout is a different field (whether
// an author is a person or an organisation) and is left alone.
function withoutKind(element) {
  if (!element.elements) return element;
  return {
    ...element,
    elements: element.elements
      .filter((child) => !(child.type === 'Control' && child.scope === '#/properties/@type'))
      .map(withoutKind),
  };
}

// Also a choice made here: a new record starts with its language set to English, which the
// author can change.
export function correctDefaults(defaults) {
  return { ...defaults, 'schema:inLanguage': 'en' };
}

// A defect: a new variable's description starts as the word "missing", which is then saved and
// submitted as if the author had written it.
export function correctSchema(schema) {
  const out = structuredClone(schema);
  // A choice made here: a keyword may be text or a term from a vocabulary, as the profile
  // allows. The copied form schema takes text only.
  const keywords = out.properties?.['schema:keywords'];
  if (keywords?.items?.type === 'string') keywords.items = { anyOf: [{ type: 'string' }, { type: 'object' }] };
  // A choice made here: a distribution's kind is one word the form holds (the schema wants a list,
  // which the server adds on save), shown by a custom control (renderers.jsx) as a plain menu.
  const dist = out.properties?.['schema:distribution']?.items?.properties;
  if (dist?.['@type']) {
    dist['@type'] = { type: 'string', enum: ['schema:DataDownload', 'schema:WebAPI'], default: 'schema:DataDownload' };
  }
  const description = out.properties?.['schema:variableMeasured']?.items?.properties?.['schema:description'];
  if (description?.default === 'missing') delete description.default;
  return out;
}
