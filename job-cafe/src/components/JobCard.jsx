import React from 'react';
import { Box, Button, Card, CardContent, CardActions, Chip, Typography } from '@mui/material';

export default function JobCard({ job, onView }) {
  const applyHref = job?.apply_url || job?.url || '';

  return (
    <Card
      elevation={0}
      sx={{
        backgroundColor: '#111827',
        borderRadius: '16px',
        border: '1px solid rgba(255,255,255,0.10)',
        transition: 'transform 200ms ease, box-shadow 200ms ease, border-color 200ms ease',
        '&:hover': {
          transform: 'translateY(-4px)',
          boxShadow: '0 18px 45px rgba(0,0,0,0.35)',
          borderColor: 'rgba(59,130,246,0.35)',
        },
      }}
    >
      <CardContent sx={{ p: 2.1 }}>
        <Typography
          variant="h6"
          sx={{ fontWeight: 600, letterSpacing: '0.2px', color: 'text.primary' }}
        >
          {job?.title || 'Untitled'}
        </Typography>

        <Box sx={{ mt: 1.2, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
          <Chip
            size="small"
            label={job?.company || '-'}
            sx={{
              borderRadius: 999,
              backgroundColor: 'rgba(59,130,246,0.08)',
              border: '1px solid rgba(59,130,246,0.25)',
              '& .MuiChip-label': { color: 'text.primary', fontWeight: 520 },
            }}
          />
          <Chip
            size="small"
            label={job?.location || '-'}
            sx={{
              borderRadius: 999,
              backgroundColor: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.10)',
              '& .MuiChip-label': { color: 'text.secondary', fontWeight: 520 },
            }}
          />
        </Box>

        <Typography
          sx={{
            mt: 1.1,
            color: 'text.secondary',
            fontSize: 13.5,
            lineHeight: 1.45,
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {job?.description || ''}
        </Typography>
      </CardContent>

      <CardActions sx={{ p: 2.1, pt: 0 }}>
        <Button
          onClick={onView}
          variant="outlined"
          sx={{
            borderRadius: 999,
            py: 1,
            px: 2.1,
            fontWeight: 700,
          }}
        >
          Details
        </Button>
        <Button
          component="a"
          href={applyHref}
          target="_blank"
          rel="noreferrer"
          variant="contained"
          disableElevation
          sx={{
            borderRadius: 999,
            bgcolor: 'primary.main',
            py: 1,
            px: 2.1,
            fontWeight: 700,
            '&:hover': {
              bgcolor: 'primary.main',
              filter: 'brightness(1.05)',
            },
          }}
        >
          Apply
        </Button>
      </CardActions>
    </Card>
  );
}

