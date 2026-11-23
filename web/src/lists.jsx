// Compact controls for a field that takes several values: one box, each value a small tag that
// can be removed, in place of the stock list with a row and a text box for every value.
//
//   TextList         any list of text (other identifiers, time covered, publishing policies)
//   InformationType  the same, offering examples as the author types
//   Keywords         text, or a term from a named vocabulary
import { useState } from 'react';
import { Autocomplete, Box, Button, Chip, Link, Stack, TextField } from '@mui/material';

const TERM = 'schema:DefinedTerm';
const isTerm = (value) => value !== null && typeof value === 'object';
// What a value is shown as. A term is shown by its name; a list copied from elsewhere may hold
// terms that have only a code or an address.
const shownAs = (value) =>
  (isTerm(value)
    ? value['schema:name'] || value['schema:termCode'] || value['schema:identifier'] || value['@id'] || 'Unnamed term'
    : String(value));
const addressOf = (value) => (typeof value === 'string' ? value : value?.['@id']);
const whereFrom = (term) =>
  [addressOf(term['schema:inDefinedTermSet']), addressOf(term['schema:identifier'])].filter(Boolean).join(' · ');

// Typed text is trimmed, blanks are dropped, and the same text is not kept twice. Terms pass
// through as they are.
function tidy(values) {
  const seen = new Set();
  const out = [];
  for (const value of values) {
    if (isTerm(value)) {
      out.push(value);
      continue;
    }
    const text = String(value).trim();
    if (text && !seen.has(text)) {
      seen.add(text);
      out.push(text);
    }
  }
  return out;
}

function ValueList({ values, onChange, options = [], label, helperText, disabled }) {
  return (
    <Autocomplete
      multiple
      freeSolo
      // Text typed and left without pressing Enter is kept as a value, not thrown away.
      autoSelect
      filterSelectedOptions
      options={options}
      disabled={disabled}
      value={values}
      getOptionLabel={shownAs}
      onChange={(_, next) => onChange(tidy(next))}
      renderTags={(tags, getTagProps) =>
        tags.map((tag, index) => {
          const { key, ...props } = getTagProps({ index });
          // A term from a vocabulary is outlined, and says where it is from when pointed at.
          return isTerm(tag)
            ? <Chip key={key} label={shownAs(tag)} size="small" variant="outlined" color="primary" title={whereFrom(tag)} {...props} />
            : <Chip key={key} label={tag} size="small" {...props} />;
        })
      }
      renderInput={(params) => <TextField {...params} label={label} helperText={helperText} sx={{ my: 1 }} />}
    />
  );
}

const listOf = (data) => (Array.isArray(data) ? data : []);

export function TextList({ data, handleChange, path, label, description, enabled, visible }) {
  if (visible === false) return null;
  return (
    <ValueList
      values={listOf(data)}
      onChange={(next) => handleChange(path, next)}
      label={label}
      helperText={description}
      disabled={enabled === false}
    />
  );
}

// Examples only: a seed list of analytical techniques. Anything else can be typed.
const INFORMATION_TYPES = [
  'Calorimetry--Differential scanning',
  'Chromatography--Ion',
  'Diffraction--X-ray',
  'Geochronology--40Ar/39Ar',
  'Mass spectrometry--Accelerator',
  'Mass spectrometry--Fourier transform ion cyclotron resonance',
  'Mass spectrometry--Gas chromatography',
  'Mass spectrometry--Inductively coupled plasma, high-resolution',
  'Mass spectrometry--Inductively coupled plasma, multi-collector',
  'Mass spectrometry--Inductively coupled plasma, quadrupole',
  'Mass spectrometry--Isotope ratio, elemental analysis',
  'Mass spectrometry--Isotope ratio, laser-assisted fluorination (bulk oxygen)',
  'Mass spectrometry--Secondary ion',
  'Mass spectrometry--Secondary ion, nanoscale',
  'Mass spectrometry--Secondary ion, time-of-flight',
  'Mass spectrometry--Static, noble gas and nitrogen',
  'Mass spectrometry--Two-step laser, microprobe',
  'Microanalysis--Electron microprobe (EPMA)',
  'Microscopy--Scanning electron',
  'Microscopy--Transmission electron',
  'Microscopy--UV fluorescence',
  'Pycnometry--Gas',
  'Spectrometry--Infrared, nanoscale mapping',
  'Spectrometry--Optical emission, inductively coupled plasma',
  'Spectrometry--Raman vibrational',
  'Spectrometry--Visible, near-, and mid-infrared',
  'Spectrometry--X-ray absorption near edge structure (XANES)',
  'Tomography--X-ray computed',
];

export function InformationType({ data, handleChange, path, label, description, enabled, visible }) {
  if (visible === false) return null;
  return (
    <ValueList
      values={listOf(data)}
      onChange={(next) => handleChange(path, next)}
      options={INFORMATION_TYPES}
      label={label}
      helperText={description}
      disabled={enabled === false}
    />
  );
}

const NO_TERM = { name: '', vocabulary: '', address: '' };

export function Keywords({ data, handleChange, path, label, description, enabled, visible }) {
  const [adding, setAdding] = useState(false);
  const [term, setTerm] = useState(NO_TERM);
  if (visible === false) return null;
  const values = listOf(data);
  const field = (key) => ({
    size: 'small',
    value: term[key],
    onChange: (e) => setTerm({ ...term, [key]: e.target.value }),
  });

  function addTerm(e) {
    e.preventDefault();
    const entry = { '@type': [TERM], 'schema:name': term.name.trim() };
    if (term.vocabulary.trim()) entry['schema:inDefinedTermSet'] = term.vocabulary.trim();
    if (term.address.trim()) entry['schema:identifier'] = term.address.trim();
    handleChange(path, [...values, entry]);
    setTerm(NO_TERM);
    setAdding(false);
  }

  return (
    <Box>
      <ValueList
        values={values}
        onChange={(next) => handleChange(path, next)}
        label={label}
        helperText={description}
        disabled={enabled === false}
      />
      {!adding ? (
        <Link component="button" type="button" variant="body2" onClick={() => setAdding(true)} data-testid="add-term">
          Add a term from a vocabulary
        </Link>
      ) : (
        <Stack component="form" onSubmit={addTerm} direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'flex-start' } }}>
          <TextField label="Term" required autoFocus {...field('name')} />
          <TextField label="Vocabulary" helperText="Its name or web address" sx={{ flex: 1 }} {...field('vocabulary')} />
          <TextField label="Term's web address" helperText="If it has one" sx={{ flex: 1 }} {...field('address')} />
          <Button type="submit" variant="outlined" disabled={!term.name.trim()}>Add</Button>
          <Button onClick={() => { setAdding(false); setTerm(NO_TERM); }}>Cancel</Button>
        </Stack>
      )}
    </Box>
  );
}
