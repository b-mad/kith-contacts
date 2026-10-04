# Vendored assets (N-04: nothing is loaded from outside the app)

| File | Package | Version | Licence |
| --- | --- | --- | --- |
| `leaflet/leaflet.js`, `leaflet/leaflet.css`, `leaflet/images/` | leaflet | 1.9.4 | BSD-2-Clause |
| `leaflet/leaflet.markercluster.js`, `leaflet/MarkerCluster*.css` | leaflet.markercluster | 1.5.3 | MIT |
| `topojson-client.min.js` | topojson-client | 3.1.0 | ISC |
| `geo/states-10m.json`, `geo/counties-10m.json` | us-atlas (US Census Bureau cartographic boundaries, public domain) | 3.0.1 | ISC |
| `geo/countries-110m.json` | world-atlas (Natural Earth, public domain) | 2.0.2 | ISC |

Copied from the npm packages' `dist/` folders unchanged (ADR-0023). To update, install the
new versions with npm and copy the same files over, then update this table.

Place data for addresses: US ZIP codes come from the `zipcodes` Python package (MIT; data
from GeoNames CC BY 4.0, USPS and unitedstateszipcodes.org); other countries from
`app/data/world_cities.tsv.gz`, built from GeoNames cities15000 (CC BY 4.0) by
`scripts/geodata.py`.
