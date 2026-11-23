// A group of fields with a heading that folds it shut and opens it again, in place of the stock
// card that is always open. Sections start open, so nothing is hidden until the author hides it.
// One button closes or opens them all, as GeoNetwork's editor has.
import { useEffect, useState } from 'react';
import { rankWith, uiTypeIs } from '@jsonforms/core';
import { MaterialLayoutRenderer } from '@jsonforms/material-renderers';
import { withJsonFormsLayoutProps } from '@jsonforms/react';
import { Accordion, AccordionDetails, AccordionSummary, Button, Typography } from '@mui/material';
import ExpandMore from '@mui/icons-material/ExpandMore';

// Whether sections are open, remembered across tabs: a tab's sections are built when it is shown.
let allOpen = true;
const sections = new Set();

function Section({ uischema, label, visible, ...props }) {
  const [open, setOpen] = useState(allOpen);
  useEffect(() => {
    sections.add(setOpen);
    return () => sections.delete(setOpen);
  }, []);
  if (visible === false) return null;
  return (
    <Accordion expanded={open} onChange={(_, next) => setOpen(next)} disableGutters variant="outlined" sx={{ mb: 1, '&:before': { display: 'none' } }}>
      <AccordionSummary expandIcon={<ExpandMore />} sx={{ minHeight: 40, '& .MuiAccordionSummary-content': { my: 0.75 } }}>
        <Typography variant="subtitle1" component="h2">{label || uischema.label}</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0 }}>
        <MaterialLayoutRenderer {...props} visible elements={uischema.elements} />
      </AccordionDetails>
    </Accordion>
  );
}

export function SectionsToggle() {
  const [open, setOpen] = useState(allOpen);
  const toggle = () => {
    allOpen = !open;
    setOpen(allOpen);
    sections.forEach((set) => set(allOpen));
  };
  return <Button onClick={toggle} data-testid="sections-toggle">{open ? 'Close all sections' : 'Open all sections'}</Button>;
}

export const sectionRenderer = { tester: rankWith(10, uiTypeIs('Group')), renderer: withJsonFormsLayoutProps(Section) };
