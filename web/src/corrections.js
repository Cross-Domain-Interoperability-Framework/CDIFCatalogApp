// Corrections laid over the form files copied from metadataBuildingBlocks, which are not edited
// here. Each undoes one known defect in those files. When a refresh of the files brings the
// fix, delete the correction: docs/form-inventory.md lists the defects and where they are filed.

// The layout addresses what a related link points to as "target"; the schema's property is
// "schema:target". With the wrong name the two fields show nothing that can be filled in.
export function correctLayout(uischema) {
  return JSON.parse(
    JSON.stringify(uischema).replaceAll('"#/properties/target/', '"#/properties/schema:target/'),
  );
}

// A new variable's description starts as the word "missing", which is then saved and submitted
// as if the author had written it.
export function correctSchema(schema) {
  const out = structuredClone(schema);
  const description = out.properties?.['schema:variableMeasured']?.items?.properties?.['schema:description'];
  if (description?.default === 'missing') delete description.default;
  return out;
}
