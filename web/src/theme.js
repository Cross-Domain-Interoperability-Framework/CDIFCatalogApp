// The form's sizes. The component library's defaults are generous: 16px text in 56px boxes, about
// seven fields to a screen. These follow the compact profile the CEDAR Embeddable Editor
// documents for its own controls (its STYLING.md): a single-line box 36px high, 14px text on a
// 21px line, 4px corners. A box holding several lines or several values grows as it needs to.
import { createTheme } from '@mui/material';

const LINE = 21;
const BOX = 36;
const PAD = (BOX - LINE) / 2;

export default createTheme({
  typography: {
    fontSize: 12.25, // the library scales this to 14px body text
    h5: { fontSize: '1.25rem' },
    h6: { fontSize: '1rem', fontWeight: 600 },
    subtitle1: { fontSize: '0.9375rem', fontWeight: 600 },
  },
  shape: { borderRadius: 4 },
  components: {
    // The small gap keeps one field's help line from touching the next field's box.
    MuiFormControl: { defaultProps: { size: 'small' }, styleOverrides: { root: { marginTop: 6 } } },
    // The date fields come from a separate package with its own names for the same things.
    MuiPickersTextField: { defaultProps: { size: 'small' } },
    MuiPickersOutlinedInput: { styleOverrides: { root: { fontSize: 14, minHeight: BOX }, sectionsContainer: { paddingTop: PAD, paddingBottom: PAD } } },
    MuiPickersInputBase: { styleOverrides: { sectionsContainer: { paddingTop: PAD, paddingBottom: PAD } } },
    MuiTextField: { defaultProps: { size: 'small' } },
    MuiAutocomplete: {
      defaultProps: { size: 'small' },
      styleOverrides: {
        // With tags inside, the box keeps one line's height until the tags wrap.
        inputRoot: { paddingTop: 5, paddingBottom: 5 },
      },
    },
    MuiButton: { defaultProps: { size: 'small' } },
    MuiOutlinedInput: {
      styleOverrides: {
        root: { fontSize: 14, lineHeight: `${LINE}px` },
        input: { height: LINE, paddingTop: PAD, paddingBottom: PAD },
        inputMultiline: { paddingTop: 0, paddingBottom: 0 },
        multiline: { paddingTop: PAD, paddingBottom: PAD },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: { fontSize: 14, lineHeight: `${LINE}px` },
        // Where the label rests inside an empty box of this height.
        outlined: { '&.MuiInputLabel-sizeSmall:not(.MuiInputLabel-shrink)': { transform: `translate(14px, ${PAD}px) scale(1)` } },
      },
    },
    MuiFormHelperText: { styleOverrides: { root: { fontSize: 12, marginTop: 2, lineHeight: 1.35 } } },
    MuiTab: { styleOverrides: { root: { minHeight: 40, paddingTop: 8, paddingBottom: 8 } } },
    MuiTabs: { styleOverrides: { root: { minHeight: 40 } } },
    MuiCardHeader: { styleOverrides: { root: { paddingBottom: 0 } } },
    MuiCardContent: { styleOverrides: { root: { paddingTop: 8, '&:last-child': { paddingBottom: 12 } } } },
  },
});
