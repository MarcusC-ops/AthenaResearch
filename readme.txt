Athena
======

Athena is a two-sided marketplace for health research studies in Singapore.
This hand-in uses Python 3.12 or newer, Django 5.2, SQLite, server-rendered
templates, Bootstrap and the two trained random-forest models in ml/models/.

Setup on macOS or Linux
-----------------------
From the workspace root:

    python3 --version
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cd athenaproj
    ../.venv/bin/python manage.py migrate
    ../.venv/bin/python manage.py seed_demo
    ATHENA_DEBUG=true ../.venv/bin/python manage.py runserver

Setup on Windows
----------------
From the workspace root in PowerShell:

    py -3 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    cd athenaproj
    ..\.venv\Scripts\python manage.py migrate
    ..\.venv\Scripts\python manage.py seed_demo
    $env:ATHENA_DEBUG = "true"
    ..\.venv\Scripts\python manage.py runserver

Open the storefront at http://127.0.0.1:8000/ and the panel at
http://127.0.0.1:8000/panel/.

ATHENA_DEBUG=true turns on Django's development mode, which is what lets
runserver serve the stylesheet and images. Without it the pages load with no
styling.

Demo accounts
-------------
All accounts use the shared password: AthenaDemo2026!

    aisyah@example.com              Participant
    mrtan@example.com               Participant
    drlim@kentridge-crc.sg          Coordinator, Kent Ridge Clinical Research Centre
    priya@athena.sg                 Staff
    admin@athena.sg                 Admin

The seed command is safe to run more than once. It creates or updates the
catalogue and demonstration data without creating duplicate records.

Retraining the models
---------------------
From inside athenaproj/, run:

    ../.venv/bin/python -m jupyter nbconvert --to notebook --execute --inplace ml/notebooks/ml1_interest.ipynb
    ../.venv/bin/python -m jupyter nbconvert --to notebook --execute --inplace ml/notebooks/ml2_screening.ipynb

Testing
-------
From inside athenaproj/:

    ../.venv/bin/python manage.py test

Development security settings
-----------------------------
`manage.py check --deploy` intentionally reports the development-only
SECRET_KEY, HTTPS redirect and HSTS settings. Do not use this configuration
for a public deployment. Set a production secret key and configure HTTPS,
secure cookies and HSTS before deploying.
