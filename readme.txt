Athena: setup
create and activate .venv
pip install -r requirements.txt
cd athenaproj
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py runserver
open http://127.0.0.1:8000/