import React from 'react';
import {
  Box,
  Button,
  Paper,
  TextField,
  InputAdornment,
  Typography,
} from '@mui/material';
import BusinessCenterIcon from '@mui/icons-material/BusinessCenter';
import SearchIcon from '@mui/icons-material/Search';
import RoomOutlinedIcon from '@mui/icons-material/RoomOutlined';
import LocalOfferOutlinedIcon from '@mui/icons-material/LocalOfferOutlined';

function GlassTextField({ label, placeholder, value, onChange, icon }) {
  return (
    <TextField
      variant="outlined"
      label={label}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      size="small"
      fullWidth
      InputProps={{
        startAdornment: (
          <InputAdornment position="start" sx={{ color: 'text.secondary', ml: 0.25 }}>
            {icon}
          </InputAdornment>
        ),
      }}
      sx={{
        '& .MuiOutlinedInput-root': {
          borderRadius: 999,
          backgroundColor: 'rgba(255,255,255,0.03)',
          '& fieldset': {
            borderColor: 'divider',
            transition: 'border-color 160ms ease, box-shadow 160ms ease',
          },
          '&:hover fieldset': {
            borderColor: 'rgba(59,130,246,0.55)',
          },
          '&.Mui-focused fieldset': {
            borderColor: 'rgba(59,130,246,0.8)',
            boxShadow: '0 0 0 4px rgba(59,130,246,0.15)',
          },
        },
        '& .MuiInputBase-input': {
          color: 'text.primary',
        },
        '& .MuiFormLabel-root': {
          color: 'text.secondary',
          letterSpacing: '0.2px',
        },
      }}
    />
  );
}

export default function SearchBar({ filters, setFilters, onSearch }) {
  function onChange(key) {
    return (e) => {
      setFilters((prev) => ({
        ...prev,
        [key]: e.target.value,
      }));
    };
  }

  function onSubmit(e) {
    e.preventDefault();
    onSearch();
  }

  return (
    <Box sx={{ mt: 0 }}>
      <Paper
        elevation={0}
        component="form"
        onSubmit={onSubmit}
        sx={{
          px: { xs: 1.25, sm: 1.75 },
          py: { xs: 1, sm: 1.25 },
          borderRadius: 999,
          border: '1px solid rgba(255,255,255,0.10)',
          background: 'rgba(255,255,255,0.04)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
        }}
      >
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1fr auto' },
            gap: 1,
            alignItems: 'center',
          }}
        >
          <GlassTextField
            label="Company"
            placeholder="e.g., Google"
            value={filters.company}
            onChange={onChange('company')}
            icon={<BusinessCenterIcon fontSize="small" />}
          />

          <GlassTextField
            label="Keyword"
            placeholder="e.g., engineer"
            value={filters.keyword}
            onChange={onChange('keyword')}
            icon={<LocalOfferOutlinedIcon fontSize="small" />}
          />

          <GlassTextField
            label="Location"
            placeholder="e.g., remote / London"
            value={filters.location}
            onChange={onChange('location')}
            icon={<RoomOutlinedIcon fontSize="small" />}
          />

          <Button
            type="submit"
            variant="contained"
            disableElevation
            startIcon={<SearchIcon />}
            sx={{
              borderRadius: 999,
              px: 2,
              height: 40,
              bgcolor: 'primary.main',
              '&:hover': {
                bgcolor: 'primary.main',
                filter: 'brightness(1.05)',
              },
              fontWeight: 650,
            }}
          >
            <Typography variant="button" sx={{ fontWeight: 650, letterSpacing: '0.2px' }}>
              Search
            </Typography>
          </Button>
        </Box>
      </Paper>
    </Box>
  );
}


