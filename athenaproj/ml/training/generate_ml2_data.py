"""Generate deterministic synthetic applications for ML-2."""

from pathlib import Path

import numpy as np
import pandas as pd


def main():
    rng = np.random.default_rng(42)
    rows = 8000
    data = {
        'age': rng.integers(21, 76, rows),
        'sex': rng.choice(['female', 'male'], rows),
        'bmi': np.clip(rng.normal(24, 4, rows), 16, 42).round(1),
        'smoker': rng.binomial(1, 0.15, rows),
        'num_conditions': np.clip(rng.poisson(0.6, rows), 0, 5),
        'prior_completed': np.clip(rng.poisson(0.5, rows), 0, 5),
        'prior_no_shows': np.clip(rng.poisson(0.3, rows), 0, 4),
        'study_type': rng.choice(
            ['interventional', 'observational', 'behavioural'],
            rows, p=[0.40, 0.35, 0.25],
        ),
        'accepts_healthy_volunteers': rng.binomial(1, 0.5, rows),
        'num_criteria': rng.integers(1, 11, rows),
        'age_range_width': rng.integers(10, 61, rows),
        'total_visits': rng.integers(1, 13, rows),
        'duration_weeks': rng.integers(1, 53, rows),
        'region_match': rng.binomial(1, 0.45, rows),
        'availability_match': rng.binomial(1, 0.55, rows),
        'preferred_answer_share': rng.choice([0, .33, .5, .67, 1.0], rows),
        'bmi_near_limit': rng.binomial(1, 0.15, rows),
    }
    data['phase'] = np.where(
        data['study_type'] == 'interventional',
        rng.choice(['phase_1', 'phase_2', 'phase_3', 'phase_4'], rows),
        'not_applicable',
    )
    z = (
        -0.35 + 0.9 * data['region_match']
        + 0.8 * data['availability_match']
        + 1.6 * (data['preferred_answer_share'] - 0.5)
        + 0.35 * data['prior_completed']
        - 0.8 * data['prior_no_shows']
        - 0.7 * data['bmi_near_limit']
        - 0.4 * data['smoker']
        - 0.08 * (data['num_criteria'] - 5)
        - 0.03 * (data['total_visits'] - 6)
        + 0.3 * data['accepts_healthy_volunteers']
        - 0.15 * data['num_conditions']
    )
    probability = 1 / (1 + np.exp(-z))
    data['passed'] = (rng.random(rows) < probability).astype(int)
    output = Path(__file__).resolve().parents[1] / 'data' / 'ml2_applications.csv'
    pd.DataFrame(data).to_csv(output, index=False)


if __name__ == '__main__':
    main()
