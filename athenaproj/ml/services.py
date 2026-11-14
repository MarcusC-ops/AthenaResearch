"""The only module that loads model files and makes predictions."""

import json

import pandas as pd
from django.conf import settings
import joblib

from core.models import PredictionLog


MODEL_DIR = settings.BASE_DIR / 'ml' / 'models'
RAW_FEATURES = [
    'age', 'sex', 'employment', 'education', 'region', 'smoker', 'bmi',
    'activity_level', 'flag_diabetes', 'flag_hypertension',
    'flag_high_cholesterol', 'flag_respiratory', 'flag_mental', 'flag_sleep',
    'flag_skin', 'motivation', 'availability', 'max_travel_minutes',
]
CONDITION_FLAGS = RAW_FEATURES[8:15]


def build_ml1_features(profile):
    flags = {name: 0 for name in CONDITION_FLAGS}
    for condition in profile.conditions.all():
        if condition.ml_flag:
            flags[f'flag_{condition.ml_flag}'] = 1
    return {
        'age': profile.age,
        'sex': profile.sex,
        'employment': profile.employment,
        'education': profile.education,
        'region': profile.region.code,
        'smoker': int(profile.smoker),
        'bmi': float(profile.bmi),
        'activity_level': profile.activity_level,
        **flags,
        'motivation': profile.motivation,
        'availability': profile.availability,
        'max_travel_minutes': int(profile.max_travel_minutes),
    }


def _write_prediction_log(profile, version, features, output, succeeded, error=''):
    try:
        PredictionLog.objects.create(
            model_name=PredictionLog.ModelName.ML1,
            model_version=version,
            participant=profile,
            features=features,
            output=output,
            succeeded=succeeded,
            error_message=error,
        )
    except Exception:
        pass


def predict_interest(profile):
    features = {}
    version = ''
    try:
        model = joblib.load(MODEL_DIR / 'ml1_interest.joblib')
        with (MODEL_DIR / 'ml1_interest_meta.json').open(encoding='utf-8') as file:
            metadata = json.load(file)
        version = metadata['version']
        features = build_ml1_features(profile)
        frame = pd.DataFrame([features])
        encoded = pd.get_dummies(frame)
        encoded = encoded.reindex(columns=metadata['feature_columns'], fill_value=0)
        probabilities = model.predict_proba(encoded)[0]
        classes = list(model.classes_)
        ranked = sorted(
            zip(classes, probabilities), key=lambda item: item[1], reverse=True
        )[:3]
        top_three = [
            {'category': category, 'probability': float(probability)}
            for category, probability in ranked
        ]
        output = {'top_three': top_three}
        _write_prediction_log(profile, version, features, output, True)
        return {'top_three': top_three, 'model_version': version}
    except Exception as error:
        _write_prediction_log(profile, version, features, {}, False, str(error))
        return None


def model_health():
    try:
        joblib.load(MODEL_DIR / 'ml1_interest.joblib')
        with (MODEL_DIR / 'ml1_interest_meta.json').open(encoding='utf-8') as file:
            json.load(file)
    except Exception:
        return {'ml1': False}
    return {'ml1': True}
