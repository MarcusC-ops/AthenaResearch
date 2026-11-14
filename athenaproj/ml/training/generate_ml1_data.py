from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / 'data' / 'ml1_participants.csv'


def main():
    rng = np.random.default_rng(42)
    rows = 3000
    age = rng.integers(21, 76, rows)
    sex = rng.choice(['female', 'male'], rows)
    employment = rng.choice(
        ['student', 'full_time', 'part_time', 'not_working', 'retired'], rows
    )
    education = rng.choice(
        ['primary', 'secondary', 'post_secondary', 'degree', 'postgraduate'], rows
    )
    region = rng.choice(['C', 'N', 'NE', 'E', 'W'], rows)
    smoker = (rng.random(rows) < 0.15).astype(int)
    bmi = np.clip(rng.normal(23.5, 4, rows), 16, 42)
    activity_level = rng.choice(
        ['low', 'moderate', 'high'], rows, p=[0.35, 0.45, 0.20]
    )
    flags = {
        'flag_diabetes': rng.random(rows) < (0.08 + 0.12 * (age >= 50)),
        'flag_hypertension': rng.random(rows) < (0.10 + 0.15 * (age >= 50)),
        'flag_high_cholesterol': rng.random(rows) < 0.12,
        'flag_respiratory': rng.random(rows) < 0.10,
        'flag_mental': rng.random(rows) < 0.12,
        'flag_sleep': rng.random(rows) < 0.10,
        'flag_skin': rng.random(rows) < 0.08,
    }
    motivation = rng.choice(
        ['help_research', 'health_check', 'compensation', 'learn'], rows
    )
    availability = rng.choice(
        ['weekday_daytime', 'weekday_evenings', 'weekends', 'flexible'], rows
    )
    max_travel_minutes = rng.choice([15, 30, 45, 60], rows)

    scores = {
        'metabolic': (
            3 * flags['flag_diabetes'] + 2 * (bmi >= 27.5)
            + (age >= 45) + (activity_level == 'low')
        ),
        'heart': (
            3 * flags['flag_hypertension'] + 2 * flags['flag_high_cholesterol']
            + (age >= 50) + smoker
        ),
        'mental_health': (
            3 * flags['flag_mental'] + (age < 35) + (employment == 'student')
        ),
        'sleep': (
            3 * flags['flag_sleep'] + (availability == 'weekday_evenings')
            + 0.5 * (employment == 'full_time')
        ),
        'respiratory': (
            3 * flags['flag_respiratory'] + smoker + flags['flag_skin']
        ),
        'womens_health': (
            2.5 * ((sex == 'female') & (age >= 21) & (age <= 50))
            + (motivation == 'health_check')
        ),
        'cognitive': (
            2 * (age >= 60) + np.isin(education, ['degree', 'postgraduate'])
            + (motivation == 'learn')
        ),
        'lifestyle': (
            2 * (activity_level == 'low') + ((bmi >= 23) & (bmi < 27.5))
            + (motivation == 'learn')
        ),
        'healthy_phase1': (
            3 * (~np.logical_or.reduce(list(flags.values())) & (age >= 21) & (age <= 45))
            + (motivation == 'compensation') + (availability == 'flexible')
        ),
    }
    score_frame = pd.DataFrame(scores)
    score_frame += rng.normal(0, 1.0, score_frame.shape)
    labels = score_frame.idxmax(axis=1)

    data = pd.DataFrame({
        'age': age,
        'sex': sex,
        'employment': employment,
        'education': education,
        'region': region,
        'smoker': smoker,
        'bmi': np.round(bmi, 1),
        'activity_level': activity_level,
        **{name: values.astype(int) for name, values in flags.items()},
        'motivation': motivation,
        'availability': availability,
        'max_travel_minutes': max_travel_minutes,
        'label': labels,
    })
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(DATA_PATH, index=False)


if __name__ == '__main__':
    main()
