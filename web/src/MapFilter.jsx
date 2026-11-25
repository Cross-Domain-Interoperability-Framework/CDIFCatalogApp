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

// The three things the map draws, each in its own colour: the box the reader searches with, the
// area of each record on the page, and the one record the reader is pointing at in the list.
const SEARCH_BOX = { color: '#1976d2', weight: 2, fillOpacity: 0.08 };
const RESULT = { color: '#78909c', weight: 1, fillOpacity: 0.05, interactive: false };
const RESULT_HILITE = { color: '#ef6c00', weight: 2, fillOpacity: 0.2, interactive: false };

// bounds [[s, w], [n, e]] from a [w, s, e, n] box.
const boundsOf = ([w, s, e, n]) => [[s, w], [n, e]];

// A map that both filters by area and shows where the results are. `value` is the search box as a
// "west,south,east,north" string (empty for none) and `onChange` is given the new string, or ''
// when it is cleared. `results` are the records on the page, each {id, bbox:[w,s,e,n]|null}; their
// areas are drawn faintly, and the one whose id is `highlightId` stands out.
export function MapFilter({ value, onChange, results = [], highlightId = null }) {
  const elementRef = useRef(null);
  const mapRef = useRef(null);
  const boxRef = useRef(null);       // the search box the reader draws
  const resultsRef = useRef(null);   // a layer group of the results' areas
  const rectsRef = useRef({});       // id -> that record's rectangle, for highlighting
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
    resultsRef.current = L.layerGroup().addTo(map);

    let start = null;
    const down = (e) => {
      if (!drawingRef.current) return;
      start = e.latlng;
      map.dragging.disable();
      if (boxRef.current) { boxRef.current.remove(); boxRef.current = null; }
    };
    const move = (e) => {
      if (!drawingRef.current || !start) return;
      const bounds = L.latLngBounds(start, e.latlng);
      if (boxRef.current) boxRef.current.setBounds(bounds);
      else boxRef.current = L.rectangle(bounds, SEARCH_BOX).addTo(map);
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

  // show the search box, drawn or set from outside
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const box = parse(value);
    if (boxRef.current) { boxRef.current.remove(); boxRef.current = null; }
    if (box) boxRef.current = L.rectangle(boundsOf(box), SEARCH_BOX).addTo(map);
  }, [value]);

  // draw each result's area, and fit the view to them when the reader has not set a search box
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    resultsRef.current.clearLayers();
    rectsRef.current = {};
    const corners = [];
    for (const r of results) {
      const box = r.bbox && parse(r.bbox.join(','));
      if (!box) continue;
      const [w, s, e, n] = box;
      const rect = L.rectangle(boundsOf(box), RESULT);
      resultsRef.current.addLayer(rect);
      rectsRef.current[r.id] = rect;
      corners.push([s, w], [n, e]);
    }
    if (corners.length && !parse(value)) {
      map.fitBounds(L.latLngBounds(corners), { padding: [20, 20], maxZoom: 6 });
    }
  }, [results, value]);

  // lift the record the reader is pointing at
  useEffect(() => {
    for (const [id, rect] of Object.entries(rectsRef.current)) {
      if (id === String(highlightId)) { rect.setStyle(RESULT_HILITE); rect.bringToFront(); }
      else rect.setStyle(RESULT);
    }
  }, [highlightId, results]);

  const arm = () => { drawingRef.current = true; setDrawing(true); };
  const clear = () => { drawingRef.current = false; setDrawing(false); onChange(''); };

  return (
    <Stack spacing={0.5}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          {results.length ? 'Results shown as areas on the map.' : 'Search by area.'}
        </Typography>
        <Button size="small" variant={drawing ? 'contained' : 'outlined'} onClick={arm}>
          {drawing ? 'Drag a box on the map' : value ? 'Draw a new box' : 'Draw a box'}
        </Button>
        {value && <Button size="small" onClick={clear}>Clear area</Button>}
      </Stack>
      <div
        ref={elementRef}
        data-testid="map"
        style={{ height: 320, width: '100%', borderRadius: 4, cursor: drawing ? 'crosshair' : '' }}
      />
    </Stack>
  );
}
