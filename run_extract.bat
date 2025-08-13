@echo off
call activate_env.bat
python -m scripts.routing.extract_course_data --course "Pinetree Country Club" --clubhouse-lat 34.0379 --clubhouse-lon -84.5928 --output-dir courses/pinetree_country_club
