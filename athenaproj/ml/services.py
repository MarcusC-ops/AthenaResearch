"""The only module that loads model files and makes predictions."""

import json

import pandas as pd
from django.conf import settings
import joblib

from core.models import Application, PredictionLog


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


def _write_prediction_log(
    profile, version, features, output, succeeded, error='', application=None,
    model_name=PredictionLog.ModelName.ML1,
):
    try:
        PredictionLog.objects.create(
            model_name=model_name,
            model_version=version,
            participant=profile,
            application=application,
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


ML2_RAW_FEATURES = [
    'age', 'sex', 'bmi', 'smoker', 'num_conditions', 'prior_completed',
    'prior_no_shows', 'study_type', 'phase', 'accepts_healthy_volunteers',
    'num_criteria', 'age_range_width', 'total_visits', 'duration_weeks',
    'region_match', 'availability_match', 'preferred_answer_share',
    'bmi_near_limit',
]


def build_ml2_features(application):
    profile = application.participant
    study = application.study
    questions = list(study.pre_screen_questions.all())
    answers = {
        answer.question_id: answer.answer
        for answer in application.answers.select_related('question')
    }
    preferred_questions = [
        question for question in questions if question.preferred_answer
    ]
    preferred_answer_share = (
        sum(answers.get(question.pk) == question.preferred_answer
            for question in preferred_questions) / len(preferred_questions)
        if preferred_questions else 1.0
    )
    criteria = len(questions)
    criteria += study.required_conditions.count() + study.excluded_conditions.count()
    criteria += int(study.sex_eligibility != study.SexEligibility.ALL)
    criteria += int(study.min_bmi is not None) + int(study.max_bmi is not None)
    criteria += int(study.smoker_rule != study.SmokerRule.ANY)
    criteria += int(study.regions.exists())
    region_match = int(
        profile.region_id is not None
        and study.sites.filter(region_id=profile.region_id).exists()
    )
    availability_match = int(
        application.availability == study.visit_times
        or application.availability == Application.Availability.FLEXIBLE
        or study.visit_times == study.VisitTimes.FLEXIBLE
    )
    bmi_near_limit = int(
        profile.bmi is not None and (
            (study.min_bmi is not None and abs(float(profile.bmi) - float(study.min_bmi)) <= 1.0)
            or (study.max_bmi is not None and abs(float(profile.bmi) - float(study.max_bmi)) <= 1.0)
        )
    )
    return {
        'age': profile.age,
        'sex': profile.sex,
        'bmi': float(profile.bmi),
        'smoker': int(profile.smoker),
        'num_conditions': profile.conditions.count(),
        'prior_completed': profile.applications.exclude(pk=application.pk).filter(
            status=Application.Status.COMPLETED
        ).count(),
        'prior_no_shows': 0,
        'study_type': study.study_type,
        'phase': study.phase,
        'accepts_healthy_volunteers': int(study.accepts_healthy_volunteers),
        'num_criteria': criteria,
        'age_range_width': study.max_age - study.min_age,
        'total_visits': study.total_visits,
        'duration_weeks': study.duration_weeks,
        'region_match': region_match,
        'availability_match': availability_match,
        'preferred_answer_share': preferred_answer_share,
        'bmi_near_limit': bmi_near_limit,
    }


def predict_screening(application):
    features = {}
    version = ''
    try:
        model = joblib.load(MODEL_DIR / 'ml2_screening.joblib')
        with (MODEL_DIR / 'ml2_screening_meta.json').open(encoding='utf-8') as file:
            metadata = json.load(file)
        version = metadata['version']
        features = build_ml2_features(application)
        frame = pd.DataFrame([features])
        encoded = pd.get_dummies(frame)
        encoded = encoded.reindex(columns=metadata['feature_columns'], fill_value=0)
        probability = float(model.predict_proba(encoded)[0][list(model.classes_).index(1)])
        from core.services import band_for, get_settings
        output = {
            'probability': probability,
            'band': band_for(probability, get_settings()),
        }
        _write_prediction_log(
            application.participant, version, features, output, True,
            application=application, model_name=PredictionLog.ModelName.ML2,
        )
        return {'probability': probability, 'version': version}
    except Exception as error:
        _write_prediction_log(
            application.participant, version, features, {}, False, str(error),
            application=application, model_name=PredictionLog.ModelName.ML2,
        )
        return None


def model_health():
    health = {}
    for name in ('ml1_interest', 'ml2_screening'):
        try:
            joblib.load(MODEL_DIR / f'{name}.joblib')
            with (MODEL_DIR / f'{name}_meta.json').open(encoding='utf-8') as file:
                json.load(file)
            health['ml1' if name.startswith('ml1') else 'ml2'] = True
        except Exception:
            health['ml1' if name.startswith('ml1') else 'ml2'] = False
    return health
