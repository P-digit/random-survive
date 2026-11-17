"""생존 위험도 예측 모델 (머신러닝 파트).

날씨 + 플레이어 상태 → 위험 등급(0 안전 / 1 주의 / 2 위험)을 분류하는
RandomForest 모델이다. 실제 조난 데이터가 없으므로, 생존 상식에 기반한 규칙에
노이즈를 섞어 만든 '합성 데이터'로 학습한다. (초안 단계의 한계 - README 참고)

단독 실행하면 모델을 학습하고 평가 결과를 출력한다:  python -m survival.risk_model
"""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from .config import MODEL_DIR

MODEL_PATH = MODEL_DIR / "risk_model.joblib"
FEATURES = ["temperature", "wind_speed", "precipitation", "humidity", "is_night",
            "in_wild", "health", "satiety", "hydration", "energy"]
LABELS = ["안전", "주의", "위험"]

_model = None


def make_dataset(n=20000, seed=42):
    """합성 데이터 생성: 환경/상태를 무작위로 뽑고 규칙 + 노이즈로 위험 등급을 매긴다."""
    rng = np.random.default_rng(seed)
    temperature = rng.uniform(-35, 48, n)
    wind = rng.gamma(2.0, 7.0, n).clip(0, 90)
    precipitation = np.where(rng.random(n) < 0.7, 0, rng.gamma(1.5, 3.0, n)).clip(0, 40)
    humidity = rng.uniform(5, 100, n)
    is_night = rng.integers(0, 2, n)
    in_wild = rng.integers(0, 2, n)
    health = rng.uniform(5, 100, n)
    satiety = rng.uniform(0, 100, n)
    hydration = rng.uniform(0, 100, n)
    energy = rng.uniform(0, 100, n)

    # 환경 스트레스: 쾌적 구간(10~27도)에서 멀어질수록, 바람·비가 강할수록 커진다
    cold = np.clip(10 - temperature, 0, None) / 45
    heat = np.clip(temperature - 27, 0, None) / 21
    env = 1.6 * cold + 1.4 * heat + wind / 90 + precipitation / 40
    env = env * (1 + 0.35 * is_night) * (0.45 + 0.55 * in_wild)   # 밤·야생에서 더 위험
    env += 0.25 * cold * (precipitation > 0)                      # 젖은 채 추우면 저체온 위험
    # 신체 스트레스: 수치가 낮을수록 커진다 (수분 부족이 가장 치명적)
    body = (1.2 * (1 - health / 100) + 0.7 * (1 - satiety / 100)
            + 1.1 * (1 - hydration / 100) + 0.6 * (1 - energy / 100))
    score = env + body + rng.normal(0, 0.18, n)

    y = np.digitize(score, [1.9, 2.8])  # 0 / 1 / 2
    X = np.column_stack([temperature, wind, precipitation, humidity, is_night,
                         in_wild, health, satiety, hydration, energy])
    return X, y


def train(save=True, verbose=False):
    """모델을 학습하고 (모델, 테스트 정확도)를 반환한다."""
    X, y = make_dataset()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y)
    model = RandomForestClassifier(n_estimators=150, max_depth=12, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, pred)
    if verbose:
        print(f"테스트 정확도: {accuracy:.3f}")
        print(classification_report(y_test, pred, target_names=LABELS))
        for name, imp in sorted(zip(FEATURES, model.feature_importances_), key=lambda t: -t[1]):
            print(f"  {name:14s} 중요도 {imp:.3f}")
    if save:
        import joblib
        MODEL_DIR.mkdir(exist_ok=True)
        joblib.dump(model, MODEL_PATH)
    return model, accuracy


def load_model():
    """저장된 모델을 불러온다. 없으면 그 자리에서 학습한다. (수 초 소요)"""
    global _model
    if _model is None:
        try:
            import joblib
            _model = joblib.load(MODEL_PATH)
        except Exception:
            _model, _ = train(save=True)
    return _model


def predict_risk(weather, health, satiety, hydration, energy, is_night, in_wild):
    """현재 상황의 위험 등급과 등급별 확률을 반환한다."""
    x = [[weather["temperature"], weather["wind_speed"], weather["precipitation"],
          weather["humidity"], int(is_night), int(in_wild),
          health, satiety, hydration, energy]]
    probs = load_model().predict_proba(x)[0]
    full = [0.0, 0.0, 0.0]
    for cls, p in zip(load_model().classes_, probs):
        full[int(cls)] = float(p)
    level = int(np.argmax(full))
    return {"level": level, "label": LABELS[level], "probs": full}


if __name__ == "__main__":
    train(save=True, verbose=True)
    print(f"모델 저장 완료: {MODEL_PATH}")
