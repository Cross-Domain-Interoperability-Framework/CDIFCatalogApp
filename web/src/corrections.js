// Corrections laid over the form files copied from metadataBuildingBlocks, which are not edited
// here. All but one undo a known defect in those files; when a refresh of the files brings the
// fix, delete the correction (docs/form-inventory.md lists the defects and where they are filed).
// Those that are not defects (`withoutKind`, `correctDefaults`, keywords as text or a term) are
// choices made here and say so.

// The layout addresses what a related link points to as "target"; the schema's property is
// "schema:target". With the wrong name the two fields show nothing that can be filled in.
export function correctLayout(uischema) {
  return withoutKind(JSON.parse(
    JSON.stringify(uischema).replaceAll('"#/properties/target/', '"#/properties/schema:target/'),
  ));
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
  const description = out.properties?.['schema:variableMeasured']?.items?.properties?.['schema:description'];
  if (description?.default === 'missing') delete description.default;
  return out;
}
