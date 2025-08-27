# Strategy: Enhance Setup App with Course Selection and Polygon Editor

## Goal

Refactor the `my-map-setup` application to support multiple golf courses and introduce a new view for visualizing and editing hole geofences. The `my-map-animation` app will be streamlined by removing the now-redundant "Shortcuts" tab.

## Plan

### 1. Python Launcher (`run_map_app.py`) Modifications

- **Asset Provisioning**: The script will be updated to copy all necessary assets for each discovered golf course into the `my-map-setup/public/` directory.
  - A sub-directory will be created for each course (e.g., `public/pinetree_country_club/`).
  - The following assets will be copied from `courses/<course_id>/...` to `my-map-setup/public/<course_id>/`:
    - `holes_connected.geojson`
    - `course_polygon.geojson`
    - `holes_geofenced.geojson` (from `geojson/generated/`)
- **Course Manifest**: A simplified `manifest.json` containing only the list of available courses will be generated and copied to `my-map-setup/public/`. This will populate the course selection UI.

### 2. Animation App (`my-map-animation`) Cleanup

- **Remove Shortcuts Tab**: The "Shortcuts" option will be removed from the `ViewSwitcher` component to streamline the UI and eliminate duplicated functionality.

### 3. Setup App (`my-map-setup`) Refactoring

- **Course Context**: A new React Context (`CourseContext`) will be created to manage the currently selected course and make it available throughout the application.

- **Main App Layout (`App.tsx`)**:
  - The root component will fetch `/manifest.json` to get the list of courses.
  - A `<Select>` dropdown will be added to allow users to switch between courses.
  - A `<Tabs>` component will be implemented to switch between two main views:
    1.  **Shortcuts**: The existing `ShortcutsView`.
    2.  **Polygon Editor**: A new `PolygonEditorView`.

- **Shortcuts View (`ShortcutsView.tsx`)**:
  - This view will be refactored to consume the selected course from `CourseContext`.
  - Asset URLs will be made dynamic to load the correct `holes_connected.geojson` based on the selected course (e.g., `/<course_id>/holes_connected.geojson`).

- **New Polygon Editor View (`PolygonEditorView.tsx`)**:
  - A new view will be created to display hole geofences.
  - It will use `CourseContext` to fetch and render the appropriate `holes_geofenced.geojson` file on a Mapbox map.
  - **Initial Scope**: The first version will focus on correctly loading and displaying the polygons for the selected course.
  - **Future Work**: This view is designed to be extended with editing capabilities, potentially using a library like `react-map-gl-draw`.

## Verification Checklist

- [ ] `run_map_app.py` successfully copies assets for all courses into `my-map-setup/public/`.
- [ ] A `manifest.json` with a course list exists in `my-map-setup/public/`.
- [ ] The "Shortcuts" tab is no longer visible in the `my-map-animation` app.
- [ ] The `my-map-setup` app displays a dropdown with a list of courses.
- [ ] Selecting a course from the dropdown updates the content of both the "Shortcuts" and "Polygon Editor" tabs.
- [ ] The "Shortcuts" view loads and displays the correct `holes_connected.geojson` for the selected course.
- [ ] The "Polygon Editor" view loads and displays the correct `holes_geofenced.geojson` for the selected course.
