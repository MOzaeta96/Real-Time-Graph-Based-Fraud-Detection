import os
from common_fraud.training.lgbm_nextday_trainer import NextDayTrainConfig, train_and_write_artifacts


def main():
    cfg = NextDayTrainConfig(
        pghost=os.getenv("PGHOST", "postgres"),
        pgport=int(os.getenv("PGPORT", "5432")),
        pgdatabase=os.getenv("PGDATABASE", "fraud"),
        pguser=os.getenv("PGUSER", "fraud"),
        pgpassword=os.getenv("PGPASSWORD", "fraud"),
        artifact_dir=os.getenv("ARTIFACT_DIR", "/artifacts"),
        model_version=os.getenv("MODEL_VERSION", "lgbm_nextday_v2"),
        train_start_date=os.getenv("TRAIN_START_DATE"),
        train_end_date=os.getenv("TRAIN_END_DATE"),
        recall_target=float(os.getenv("RECALL_TARGET", "0.95")),
        precision_target=float(os.getenv("PRECISION_TARGET", "0.20")),
        drift_bins=int(os.getenv("DRIFT_BINS", "10")),
    )

    train_and_write_artifacts(cfg)


if __name__ == "__main__":
    main()
