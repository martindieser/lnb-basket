import pandas as pd
import numpy as np
import xgboost as xgb

from sklearn.model_selection import TimeSeriesSplit
from sklearn.linear_model import RidgeCV, LinearRegression

from core.minutes import MinutesModel

from core.hca import model as hca_lib
from core.hca import feature_engineering as hca_feat
from core.hca.feature_engineering import prepare_itinerary_per_team

from core.minutes_forecaster import (
    models as min_models_lib,
    feature_engineering as min_feat,
    data_processing as min_proc,
)

from core.rapm import (
    model as rapm_lib,
    feature_engineering as rapm_feat,
    predict as rapm_pred,
)



class MinutesForecaster:
    def __init__(self):
        self.base_model = None
        self.stars_model = None
        self.classifier = None
        self.features_df = None
        self.history = []

    def fit(self, stints, matches):
        raw_data, self.periods = min_proc.prepare_data(stints, matches)

        last_games = (
            raw_data.sort_values("date")
            .groupby("player_id")
            .tail(1)
            .copy()
        )

        future_rows = last_games.copy()
        future_rows["id_comp"] = ""
        future_rows["date"] += pd.Timedelta(days=1)
        future_rows["match_id"] = None
        future_rows["duration"] = np.nan
        future_rows["is_starter"] = np.nan
        future_rows["periods"] = 4

        data = pd.concat([raw_data, future_rows], ignore_index=True)

        self.features_df = min_feat.build_features(data).copy()
        train_df = self.features_df.dropna(subset=["target"])

        if self.history:
            combined_history = self._prepare_history(
                self.history, self.features_df
            )
            X_cls, y_cls = min_feat.preprocess_model_history(combined_history)
            self.classifier = min_models_lib.train_classifier(X_cls, y_cls)

        cols = [c for c in self.features_df.columns if c != "target"]

        self.base_model = min_models_lib.train_base_model(
            train_df[cols], train_df["target"]
        )
        self.stars_model = min_models_lib.train_stars_model(
            train_df[cols], train_df["target"]
        )

        return self

    def predict(self, upcoming: pd.DataFrame) -> pd.DataFrame:
        pred_rows = self._get_prediction_rows(upcoming, self.features_df)

        p1 = self.base_model.predict(
            min_feat.filter_base_model_feat(pred_rows)
        )
        p2 = self.stars_model.predict(
            min_feat.filter_stars_model_feat(pred_rows)
        )

        schedule_map = pd.concat(
            [
                upcoming[["match_id", "home_id"]].rename(
                    columns={"home_id": "team_id"}
                ),
                upcoming[["match_id", "away_id"]].rename(
                    columns={"away_id": "team_id"}
                ),
            ],
            ignore_index=True,
        ).drop_duplicates(subset=["match_id", "team_id"])

        new_preds = pred_rows.drop(columns=["match_id"]).copy()
        new_preds["p1"] = p1
        new_preds["p2"] = p2
        new_preds = new_preds.merge(
            schedule_map, on="team_id", how="inner"
        )

        self.history.append(new_preds)

        if self.classifier is not None:
            X_cls, _ = min_feat.preprocess_model_history(new_preds)
            weights = self.classifier.predict_proba(X_cls)[:, 1]
            final_mins = (p1 * (1 - weights)) + (p2 * weights)
        else:
            final_mins = 0.5 * p1 + 0.5 * p2

        pred_rows["projected_minutes"] = np.maximum(final_mins, 0) * 40

        return pred_rows[["player_id", "team_id", "projected_minutes"]]

    def _prepare_history(self, history, features):
        return (
            pd.concat(history)
            .drop(columns=["target"])
            .merge(
                features[["match_id", "team_id", "player_id", "target"]],
                on=["match_id", "team_id", "player_id"],
                how="left",
            )
        )

    def _get_prediction_rows(self, upcoming, feat):
        home_teams = upcoming[["home_id", "id_comp"]].rename(
            columns={"home_id": "team_id"}
        )
        away_teams = upcoming[["away_id", "id_comp"]].rename(
            columns={"away_id": "team_id"}
        )

        unique_teams = pd.concat([home_teams, away_teams]).drop_duplicates()

        is_prediction_row = feat["match_id"].isna()
        comps = feat["id_comp"].unique()

        recent_matches = (
            feat[
                (~is_prediction_row)
                & (feat["id_comp"].isin(comps))
                & (feat["date"] < upcoming["date"].min())
            ]
            .sort_values(["team_id", "date"], ascending=[True, False])
            .groupby("team_id")
            .head(10)
        )

        recent_players = feat[
            feat["match_id"].isin(recent_matches["match_id"].unique())
        ]["player_id"].unique()

        predictions_rows = feat[
            (is_prediction_row)
            & (feat["player_id"].isin(recent_players))
            & (feat["team_id"].isin(unique_teams["team_id"].unique()))
        ].copy()

        return predictions_rows



class PlayerPriorModel:
    def __init__(self):
        self.player_stats = None

    def fit(self, matches, stints, boxscores):
        self.player_stats = rapm_feat.prepare_player_stats(
            stints, boxscores
        )

        X_p, y_p, w_p = rapm_feat.generate_features(self.player_stats)
        self.player_stats["prior"] = rapm_feat.predict_prior_kfold(
            X_p, y_p, w_p
        )

        preds = self.predict(matches, stints)
        merged = matches.merge(preds, on="match_id")

        self.residuals_ = pd.DataFrame(
            {
                "match_id": merged["match_id"],
                "y_residual": (
                    (merged["home_pts"] - merged["away_pts"])
                    - merged["expected_spread"]
                ),
            }
        )

    def predict(self, upcoming, stints) -> pd.DataFrame:
        prior_dict = self.player_stats["prior"].to_dict()

        stints = stints.copy()
        stints["home_lineup_prior"] = stints["home_lineup"].apply(
            lambda s: sum(prior_dict.get(p, 0) for p in s)
        )
        stints["away_lineup_prior"] = stints["away_lineup"].apply(
            lambda s: sum(prior_dict.get(p, 0) for p in s)
        )

        stints["prior_avg_spread"] = (
            stints["home_lineup_prior"]
            - stints["away_lineup_prior"]
        )

        expected = (
            stints.groupby("match_id")["prior_avg_spread"]
            .mean()
            .rename("expected_spread")
        )

        merged = upcoming.merge(expected, on="match_id")
        return merged[["match_id", "expected_spread"]]



class HCAModel:
    def __init__(self):
        self.model = None
        self.cols = None

    def prepare_data(self, residuals, matches):
        data = matches.merge(
            residuals[["match_id", "y_residual"]], on="match_id"
        )
        data = data.sort_values("date").reset_index(drop=True)

        y = data["y_residual"]
        X = pd.get_dummies(data["home_id"]).astype(int)
        match_ids = data["match_id"]

        return X, y, match_ids

    def fit(self, residuals, matches):
        X, y, match_ids = self.prepare_data(residuals, matches)
        self.cols = X.columns

        tscv = TimeSeriesSplit(n_splits=5)

        self.model = RidgeCV(
            alphas=[0, 5, 10, 25, 50, 75, 100],
            fit_intercept=False,
            cv=tscv,
        )
        self.model.fit(X, y)

        preds = self.model.predict(X)
        self.residuals_ = pd.DataFrame(
            {
                "match_id": match_ids,
                "y_residual": y - preds,
            }
        )
        return self

    def predict(self, upcoming) -> pd.DataFrame:
        ranking = (
            pd.Series(self.model.coef_, index=self.cols)
            .reset_index()
            .rename(columns={"index": "home_id", 0: "hca"})
        )
        return ranking[
            ranking["home_id"].isin(upcoming["home_id"].unique())
        ]



class GameContextModel:
    def __init__(self):
        self.loc = None
        self.model = None
        self.train_stats = {"mean": 0, "std": 1}

    def prepare_data(self, matches, loc):
        if loc is None:
            raise RuntimeError("Loc dataframe cannot be None")

        matches_clean = matches.dropna(
            subset=["match_id", "date", "home_id", "away_id"]
        )

        it = prepare_itinerary_per_team(matches_clean, loc)
        it = it.sort_values("date")

        it["days_rest"] = it["days_rest"].fillna(99)
        it["is_b2b"] = (it["days_rest"] <= 1).astype(int)
        it["distance_from_home"] = it["distance_from_home"].fillna(
            it["distance_from_home"].mean()
        )

        reduced_it = it[
            ["match_id", "team_id", "distance_from_home", "is_b2b"]
        ]

        df = (
            matches_clean.merge(
                reduced_it,
                left_on=["match_id", "home_id"],
                right_on=["match_id", "team_id"],
            )
            .drop(columns=["team_id"])
            .rename(
                columns={
                    "distance_from_home": "home_dist",
                    "is_b2b": "is_home_b2b",
                }
            )
            .merge(
                reduced_it,
                left_on=["match_id", "away_id"],
                right_on=["match_id", "team_id"],
            )
            .drop(columns=["team_id"])
            .rename(
                columns={
                    "distance_from_home": "away_dist",
                    "is_b2b": "is_away_b2b",
                }
            )
        )

        df["away_dist"] = df["away_dist"].fillna(0)
        df["is_away_b2b"] = df["is_away_b2b"].fillna(0)

        return df



class PlayerValuator:
    def __init__(self):
        self.priors = PlayerPriorModel()
        self.hca_model = HCAModel()
        self.game_context = GameContextModel()
        self.model = None
        self.player_idx = None

    def fit(self, stints, boxscores, matches, loc):
        self.priors.fit(matches, stints, boxscores)
        self.hca_model.fit(self.priors.residuals_, matches)

        X, y, w, self.player_idx = rapm_feat.generate_features_with_prior(
            pd.merge(stints, matches, on="match_id"),
            self.priors.player_stats,
            self.hca_model.predict(matches),
        )

        self.model = rapm_lib.train_ridge_regression(X, y, w)
        return self

    def get_rankings(self) -> pd.DataFrame:
        return rapm_pred.get_full_ranking(
            self.priors.player_stats, self.model, self.player_idx
        )


class BasketballSpreadPipeline:
    def __init__(self):
        self.minutes_model = MinutesModel()
        self.valuation_model = PlayerValuator()

    def fit(self, events, stints, boxscores, matches, loc):
        self.minutes_model.fit(boxscores, events, matches)
        self.valuation_model.fit(stints, boxscores, matches, loc)
        return self

    def predict(self, upcoming_matches: pd.DataFrame) -> pd.DataFrame:
        rankings = self.valuation_model.get_rankings()
        minutes_proj = self.minutes_model.predict_upcoming(upcoming_matches)

        team_impact = self._calculate_team_impact(
            minutes_proj, rankings
        )
        hca_impact = self.valuation_model.hca_model.predict(
            upcoming_matches
        )

        df = (
            upcoming_matches[["match_id", "home_id", "away_id"]]
            .merge(team_impact, left_on="home_id", right_on="team_id")
            .merge(
                team_impact,
                left_on="away_id",
                right_on="team_id",
                suffixes=("_home", "_away"),
            )
            .merge(hca_impact, on="home_id")
        )

        df["avg_spread"] = (
            df["weighted_rapm_home"]
            - df["weighted_rapm_away"]
            + self.valuation_model.model.intercept_
        )

        return df[["match_id", "home_id", "away_id", "avg_spread"]]

    def _calculate_team_impact(self, projections, players_ranking):
        projections["share"] = projections["expected_minutes"] / 40

        merged = projections.merge(
            players_ranking, on="player_id", how="left"
        )
        merged["total"] = merged["total"].fillna(0)
        merged["weighted_rapm"] = merged["share"] * merged["total"]

        impact = (
            merged.groupby("team_id")["weighted_rapm"]
            .sum()
            .to_frame()
        )

        return impact
