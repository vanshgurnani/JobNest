import { createTheme } from '@mui/material/styles';

const PRIMARY = '#3B82F6';
const BG_TOP = '#0B1220';
const BG_BOTTOM = '#0F172A';
const CARD_BG = '#111827';
const TEXT_PRIMARY = '#E5E7EB';
const TEXT_SECONDARY = '#9CA3AF';

export const appTheme = createTheme({
  cssVariables: false,
  shape: {
    borderRadius: 16,
  },
  palette: {
    mode: 'dark',
    primary: {
      main: PRIMARY,
      contrastText: '#ffffff',
    },
    background: {
      default: BG_TOP,
      paper: CARD_BG,
    },
    text: {
      primary: TEXT_PRIMARY,
      secondary: TEXT_SECONDARY,
    },
    divider: 'rgba(255,255,255,0.10)',
  },
  typography: {
    fontFamily:
      'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji"',
    letterSpacing: '0.2px',
    h4: {
      letterSpacing: '0.3px',
    },
    h6: {
      letterSpacing: '0.15px',
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          background: `radial-gradient(1200px 600px at 30% -20%, rgba(59,130,246,0.24), transparent 60%), linear-gradient(180deg, ${BG_TOP}, ${BG_BOTTOM})`,
          color: TEXT_PRIMARY,
        },
        '*': {
          boxSizing: 'border-box',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
        },
      },
    },

    // App-level keyframes (used by micro-interactions)
    '@keyframes fadeInUp': {
      '0%': { opacity: 0, transform: 'translate3d(0, 8px, 0)' },
      '100%': { opacity: 1, transform: 'translate3d(0, 0, 0)' },
    },
  },
});



