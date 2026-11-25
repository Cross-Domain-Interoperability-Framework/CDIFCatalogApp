import { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Button, Stack, Typography } from '@mui/material';

// A box as "west,south,east,north" of four numbers, or null if the string is empty or malformed.
function parse(value) {
  if (!value) return null;
  const n = value.split(',').map(Number);
  return n.length === 4 && n.every((x) => Number.isFinite(x)) ? n : null;
}

const round = (x) => Math.round(x * 1000) / 1000;
// The map can show past the edges of the world; keep a drawn box inside the valid ranges, or the
// server rejects it.
const lat = (y) => round(Math.max(-90, Math.min(90, y)));
const lng = (x) => round(Math.max(-180, Math.min(180, x)));
const DRAWN = { color: '#1976d2', weight: 2, fillOpacity: 0.1 };

// A map on which the reader draws one box to search by place. `value` is the current box as a
// "west,south,east,north" string (empty for none); `onChange` is given the new string, or '' when
// the box is cleared. The box drives the search; the map only reads and writes that one string.
export function MapFilter({ value, onChange }) {
  const elementRef = useRef(null);
  const mapRef = useRef(null);
  const rectRef = useRef(null);
  const drawingRef = useRef(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [drawing, setDrawing] = useState(false);

  // build the map once
  useEffect(() => {
    const map = L.map(elementRef.current, {
      maxBounds: [[-90, -180], [90, 180]], maxBoundsViscosity: 1,
    }).setView([15, 0], 1);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 18, noWrap: true,
    }).addTo(map);
    mapRef.current = map;

    let start = null;
    const down = (e) => {
      if (!drawingRef.current) return;
      start = e.latlng;
      map.dragging.disable();
      if (rectRef.current) { rectRef.current.remove(); rectRef.current = null; }
    };
    const move = (e) => {
      if (!drawingRef.current || !start) return;
      const bounds = L.latLngBounds(start, e.latlng);
      if (rectRef.current) rectRef.current.setBounds(bounds);
      else rectRef.current = L.rectangle(bounds, DRAWN).addTo(map);
    };
    const up = (e) => {
      if (!drawingRef.current || !start) return;
      const b = L.latLngBounds(start, e.latlng);
      start = null;
      drawingRef.current = false;
      setDrawing(false);
      map.dragging.enable();
      onChangeRef.current([lng(b.getWest()), lat(b.getSouth()), lng(b.getEast()), lat(b.getNorth())].join(','));
    };
    map.on('mousedown', down).on('mousemove', move).on('mouseup', up);
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // show the current box, drawn or set from outside, as the one rectangle on the map
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const box = parse(value);
    if (rectRef.current) { rectRef.current.remove(); rectRef.current = null; }
    if (box) {
      const [w, s, e, n] = box;
      rectRef.current = L.rectangle([[s, w], [n, e]], DRAWN).addTo(map);
    }
  }, [value]);

  const arm = () => { drawingRef.current = true; setDrawing(true); };
  const clear = () => { drawingRef.current = false; setDrawing(false); onChange(''); };

  return (
    <Stack spacing={0.5} sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="body2" color="text.secondary">Area on the map</Typography>
        <Button size="small" variant={drawing ? 'contained' : 'outlined'} onClick={arm}>
          {drawing ? 'Drag a box on the map' : value ? 'Draw a new box' : 'Draw a box'}
        </Button>
        {value && <Button size="small" onClick={clear}>Clear area</Button>}
      </Stack>
      <div
        ref={elementRef}
        data-testid="map"
        style={{ height: 280, width: '100%', borderRadius: 4, cursor: drawing ? 'crosshair' : '' }}
      />
    </Stack>
  );
}
