// A group of fields with a heading that folds it shut and opens it again, in place of the stock
// card that is always open. Sections start open, so nothing is hidden until the author hides it.
import { rankWith, uiTypeIs } from '@jsonforms/core';
import { MaterialLayoutRenderer } from '@jsonforms/material-renderers';
import { withJsonFormsLayoutProps } from '@jsonforms/react';
import { Accordion, AccordionDetails, AccordionSummary, Typography } from '@mui/material';
import ExpandMore from '@mui/icons-material/ExpandMore';

function Section({ uischema, label, visible, ...props }) {
  if (visible === false) return null;
  return (
    <Accordion defaultExpanded disableGutters variant="outlined" sx={{ mb: 1, '&:before': { display: 'none' } }}>
      <AccordionSummary expandIcon={<ExpandMore />} sx={{ minHeight: 40, '& .MuiAccordionSummary-content': { my: 0.75 } }}>
        <Typography variant="subtitle1" component="h2">{label || uischema.label}</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0 }}>
        <MaterialLayoutRenderer {...props} visible elements={uischema.elements} />
      </AccordionDetails>
    </Accordion>
  );
}

export const sectionRenderer = { tester: rankWith(10, uiTypeIs('Group')), renderer: withJsonFormsLayoutProps(Section) };
