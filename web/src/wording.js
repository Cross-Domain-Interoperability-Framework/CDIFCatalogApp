// Plain-language labels and one line of help for every field of the form.
//
// The form's layout file is copied from metadataBuildingBlocks and is not edited here, so our
// wording is laid over it: each control is given a key, and JSON Forms asks `translate` for that
// key's label and description. A control with no entry keeps the layout's own label.
import coreDiscovery from './wording/CoreDiscovery.json';

const WORDING = { CoreDiscovery: coreDiscovery };

// "#/properties/schema:creator/properties/@list" -> "schema:creator/@list"
const local = (scope) => scope.replace(/^#\/properties\//, '').replaceAll('/properties/', '/');

// A copy of the layout with a wording key on every control. A control inside a list's detail
// layout gets its list's key in front, since the same property name means different things in
// different lists.
export function withWordingKeys(uischema) {
  const walk = (element, parent) => {
    const out = { ...element };
    let key = parent;
    if (element.type === 'Control' && element.scope) {
      key = parent ? `${parent}/${local(element.scope)}` : local(element.scope);
      out.i18n = key;
    }
    if (element.elements) out.elements = element.elements.map((child) => walk(child, parent));
    if (element.options?.detail && typeof element.options.detail === 'object') {
      out.options = { ...element.options, detail: walk(element.options.detail, key) };
    }
    return out;
  };
  return walk(uischema, '');
}

// For the JsonForms `i18n` prop. JSON Forms asks for "<key>.label" and "<key>.description".
export function translator(profile) {
  const wording = WORDING[profile] || {};
  return (key, defaultMessage) => {
    const dot = key.lastIndexOf('.');
    const entry = wording[key.slice(0, dot)];
    const part = key.slice(dot + 1);
    if (entry && part === 'label') return entry.label ?? defaultMessage;
    if (entry && part === 'description') return entry.help ?? defaultMessage;
    return defaultMessage;
  };
}

// The label a field is known by, for the validation report.
export function labelOf(profile, key, fallback) {
  return WORDING[profile]?.[key]?.label ?? fallback;
}
