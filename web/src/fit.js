// Reshapes a CDIF record into the document the form edits.
//
// A record may use any shape its profile allows; the form's schema settles on one shape for each
// field (an identifier as text, a keyword as text, a type as one word). This walks the record
// beside the form's schema and, where the two differ, turns the record's value into the shape
// the form shows. That loses detail: a keyword from a vocabulary becomes its label. Parts the
// form has no field for are carried through unchanged, so they are still in the record when it
// is saved. The server does the opposite journey when it checks a form document.

const ROLE = 'schema:Role';
// For these fields an address says more than a label.
const ADDRESS_FIRST = /identifier|sameAs|url|additionalType|propertyID/i;

const kindOf = (value) => (Array.isArray(value) ? 'array' : value === null ? 'null' : typeof value);
const looksLikeAddress = (text) => /^[a-z][a-z0-9+.-]*:\/\/\S+$/i.test(text);

function resolve(schema, root) {
  const ref = schema && schema.$ref;
  if (typeof ref === 'string' && ref.startsWith('#/$defs/')) return root.$defs[ref.slice(8)] || {};
  return schema || {};
}

// Where the form's schema itself offers a choice, take the branch that already suits the value.
function branchFor(schema, value, root) {
  // A schema that states its own type uses anyOf for a rule ("one of these must be filled"),
  // not for a choice of shape.
  const branches = schema.type ? [] : (schema.anyOf || schema.oneOf || []).map((b) => resolve(b, root));
  if (!branches.length) return schema;
  const kind = kindOf(value);
  return branches.find((b) => b.type === kind || (Array.isArray(b.type) && b.type.includes(kind))) || branches[0];
}

function asText(value, key) {
  if (Array.isArray(value)) return asText(value[0], key);
  if (value && typeof value === 'object') {
    const order = ADDRESS_FIRST.test(key)
      ? ['schema:url', 'schema:value', '@id', 'schema:name']
      : ['schema:name', 'schema:url', 'schema:value', '@id'];
    const found = order.map((k) => value[k]).find((v) => typeof v === 'string' && v);
    return found === undefined ? undefined : found;
  }
  return value === undefined || value === null ? undefined : String(value);
}

function asGroup(text, properties) {
  const order = looksLikeAddress(text)
    ? ['schema:url', 'schema:identifier', 'schema:name', 'schema:description']
    : ['schema:name', 'schema:description', 'schema:url'];
  const key = order.find((k) => properties[k]);
  if (!key) return text;
  // The form gives each group the type marker its schema names; a group made here needs it too.
  const type = properties['@type'] && properties['@type'].default;
  return type ? { '@type': type, [key]: text } : { [key]: text };
}

function fit(value, given, key, root) {
  const schema = branchFor(resolve(given, root), value, root);
  if (schema.type === 'string') {
    return typeof value === 'string' ? value : asText(value, key);
  }
  if (schema.type === 'array') {
    const list = Array.isArray(value) ? value : [value];
    return list.map((item) => fit(item, schema.items, key, root)).filter((item) => item !== undefined);
  }
  if (schema.type === 'object') {
    const properties = schema.properties || {};
    // The form keeps authors as an ordered list; a record may give one author, or a plain list.
    const ordered = properties['@list'] && !(value && typeof value === 'object' && '@list' in value);
    let group = ordered ? { '@list': [].concat(value) } : Array.isArray(value) ? value[0] : value;
    if (typeof group === 'string') return asGroup(group, properties);
    if (!group || typeof group !== 'object') return group;
    // A contributor with a role is held as a role wrapping the person. The form shows one
    // person with a role beside the name.
    const types = [].concat(group['@type'] || []);
    const inner = group['schema:contributor'];
    if (types.includes(ROLE) && inner && typeof inner === 'object' && properties['schema:name']) {
      group = { ...(Array.isArray(inner) ? inner[0] : inner), 'schema:roleName': group['schema:roleName'] };
    }
    return Object.fromEntries(
      Object.entries(group)
        .map(([k, v]) => [k, properties[k] ? fit(v, properties[k], k, root) : v])
        .filter(([, v]) => v !== undefined),
    );
  }
  return value;
}

export function fitRecord(record, schema) {
  const document = fit(record, schema, '', schema);
  // The server writes these itself: the record's identity and what its catalog entry claims.
  delete document['@id'];
  const about = document['schema:subjectOf'];
  if (about && typeof about === 'object') {
    for (const k of ['@id', 'schema:about', 'dcterms:conformsTo', 'schema:additionalType']) delete about[k];
  }
  return document;
}
