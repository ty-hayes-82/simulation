from flask import Flask, request, jsonify
from pathlib import Path
import json
import shutil
from flask_cors import CORS

app = Flask(__name__)
# Allow CORS for development to avoid issues with the React dev server
CORS(app)

# The server is run from the project root, so paths are relative to that
PROJECT_ROOT = Path(__file__).parent.parent
COURSES_DIR = PROJECT_ROOT / 'my-map-setup' / 'public' / 'courses'

@app.route('/api/save-course/<course_id>', methods=['POST'])
def save_course(course_id):
    """Saves the updated GeoJSON data for a specific course."""
    # Basic security check for the course_id to prevent directory traversal attacks
    if not all(c.isalnum() or c in ['_', '-'] for c in course_id):
        return jsonify({"status": "error", "message": "Invalid course ID format"}), 400

    geojson_path = COURSES_DIR / course_id / 'holes_geofenced.geojson'

    if not geojson_path.is_file():
        # Check the legacy location as a fallback
        legacy_path = PROJECT_ROOT / 'courses' / course_id / 'geojson' / 'holes_geofenced.geojson'
        if legacy_path.is_file():
            geojson_path = legacy_path
        else:
             return jsonify({"status": "error", "message": f"File not found for course: {course_id}"}), 404

    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400

        # Create a backup of the existing file before overwriting
        backup_path = geojson_path.with_suffix('.geojson.bak')
        shutil.copy(geojson_path, backup_path)

        # Write the new data to the file with pretty printing
        with open(geojson_path, 'w') as f:
            json.dump(data, f, indent=2)

        return jsonify({"status": "success", "message": f"Successfully saved course '{course_id}'"})

    except Exception as e:
        # Log the exception for debugging
        print(f"Error saving course {course_id}: {e}")
        return jsonify({"status": "error", "message": "An unexpected error occurred."}), 500

if __name__ == '__main__':
    # Run on port 5001 to avoid conflicts with the React app's default port 3000
    app.run(debug=True, port=5001)
