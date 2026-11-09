"""Entrenamiento, evaluación temporal y explicación (SHAP) de modelos."""
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, roc_auc_score, average_precision_score, f1_score

from .config import RANDOM_STATE


def prepare_X(df: pd.DataFrame, features: list[str], top_categories: int = 30) -> pd.DataFrame:
    """Selecciona variables existentes y convierte texto a 'category' (LightGBM las maneja nativamente).
    Categorías raras se agrupan en 'Otro'."""
    cols = [c for c in features if c in df.columns]
    X = df[cols].copy()
    for c in X.columns:
        if not (pd.api.types.is_numeric_dtype(X[c]) or pd.api.types.is_bool_dtype(X[c])) \
                or c in ("dx_principal", "visit_type_concept_id"):
            top = X[c].astype(str).value_counts().index[:top_categories]
            X[c] = X[c].astype(str).where(X[c].astype(str).isin(top), "Otro").astype("category")
    return X


def temporal_split(df: pd.DataFrame, date_col: str = "visit_start_datetime", test_frac: float = 0.2):
    """Entrena con el pasado, evalúa con el futuro (evita sobreoptimismo)."""
    cut = df[date_col].quantile(1 - test_frac)
    return df[df[date_col] < cut].index, df[df[date_col] >= cut].index, cut


def train_regressor(X_tr, y_tr, X_te, y_te, **params):
    import lightgbm as lgb
    p = dict(n_estimators=800, learning_rate=0.03, num_leaves=31, min_child_samples=30,
             subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
             random_state=RANDOM_STATE, verbose=-1)
    p.update(params)
    m = lgb.LGBMRegressor(**p)
    m.fit(X_tr, y_tr, eval_set=[(X_te, y_te)],
          callbacks=[lgb.early_stopping(50, verbose=False)])
    return m


def train_classifier(X_tr, y_tr, X_te, y_te, **params):
    import lightgbm as lgb
    p = dict(n_estimators=800, learning_rate=0.03, num_leaves=31, min_child_samples=30,
             subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
             class_weight="balanced", random_state=RANDOM_STATE, verbose=-1)
    p.update(params)
    m = lgb.LGBMClassifier(**p)
    m.fit(X_tr, y_tr, eval_set=[(X_te, y_te)],
          callbacks=[lgb.early_stopping(50, verbose=False)])
    return m


def eval_regression_log(model, X_te, y_te_log) -> dict:
    """Métricas en horas reales a partir de un modelo entrenado sobre log1p(LOS)."""
    pred_h = np.expm1(model.predict(X_te))
    real_h = np.expm1(y_te_log)
    baseline = np.full_like(real_h, np.median(real_h))
    return {
        "MAE_h": round(mean_absolute_error(real_h, pred_h), 2),
        "MAE_baseline_mediana_h": round(mean_absolute_error(real_h, baseline), 2),
        "MedAE_h": round(float(np.median(np.abs(real_h - pred_h))), 2),
    }


def eval_classification(model, X_te, y_te) -> dict:
    proba = model.predict_proba(X_te)[:, 1]
    return {
        "AUC": round(roc_auc_score(y_te, proba), 3),
        "AUPRC": round(average_precision_score(y_te, proba), 3),
        "F1@0.5": round(f1_score(y_te, proba >= 0.5), 3),
        "prevalencia": round(float(np.mean(y_te)), 3),
    }


def shap_values(model, X: pd.DataFrame, max_rows: int = 5000):
    """Valores SHAP (muestra para velocidad). Devuelve (explainer, shap_values, X_muestra)."""
    import shap
    Xs = X.sample(min(max_rows, len(X)), random_state=RANDOM_STATE)
    explainer = shap.TreeExplainer(model)
    sv = explainer(Xs)
    return explainer, sv, Xs


def shap_importance_table(sv, X: pd.DataFrame) -> pd.DataFrame:
    """Importancia media |SHAP| por variable — lista para exportar a Power BI."""
    vals = sv.values if hasattr(sv, "values") else sv
    if vals.ndim == 3:  # clasificador binario en algunas versiones
        vals = vals[:, :, 1]
    return (pd.DataFrame({"variable": X.columns, "importancia_shap": np.abs(vals).mean(0)})
              .sort_values("importancia_shap", ascending=False).reset_index(drop=True))
