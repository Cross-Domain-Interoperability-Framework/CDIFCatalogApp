// The language field: a box that offers common languages and still takes any text. The record
// holds a language's short code where the text names one of the languages offered ("English"
// and "en" both become "en"), and otherwise exactly what was typed.
import { useEffect, useRef, useState } from 'react';
import { Autocomplete, TextField, createFilterOptions } from '@mui/material';

const LANGUAGES = [
  ['English', 'en'], ['Spanish', 'es'], ['French', 'fr'], ['German', 'de'], ['Chinese', 'zh'],
  ['Portuguese', 'pt'], ['Russian', 'ru'], ['Japanese', 'ja'], ['Arabic', 'ar'], ['Italian', 'it'],
];
const shownAs = ([name, code]) => `${name} (${code})`;
const OPTIONS = LANGUAGES.map(shownAs);
const narrow = createFilterOptions();

// What the record holds for a piece of text.
export function languageValue(text) {
  const typed = text.trim();
  const lower = typed.toLowerCase();
  const known = LANGUAGES.find((l) => [l[0], l[1], shownAs(l)].some((form) => form.toLowerCase() === lower));
  return known ? known[1] : typed || undefined;
}

// What the box shows for a value in the record.
function languageText(value) {
  if (typeof value !== 'string') return '';
  const known = LANGUAGES.find((l) => l[1] === value);
  return known ? shownAs(known) : value;
}

export default function Language({ data, handleChange, path, label, description, required, enabled, visible }) {
  const [text, setText] = useState(languageText(data));
  const typing = useRef(false);

  // Follow a change made elsewhere (a draft loading, the DOI pre-fill), but never rewrite the
  // box under someone typing: "En" on the way to "English" is already the code for English.
  useEffect(() => {
    if (!typing.current) setText(languageText(data));
  }, [data]);

  if (visible === false) return null;
  return (
    <Autocomplete
      freeSolo
      options={OPTIONS}
      // A box already holding one of the languages offers them all, so another can be picked
      // without clearing it first. Typing anything else narrows the list as usual.
      filterOptions={(options, state) => (OPTIONS.includes(state.inputValue) ? options : narrow(options, state))}
      disabled={enabled === false}
      inputValue={text}
      onInputChange={(_, next) => {
        setText(next);
        handleChange(path, languageValue(next));
      }}
      onFocus={() => { typing.current = true; }}
      onBlur={() => {
        typing.current = false;
        setText(languageText(languageValue(text)));
      }}
      renderInput={(params) => (
        <TextField {...params} label={label} required={required} helperText={description} sx={{ my: 1 }} />
      )}
    />
  );
}
