"""Protect benchmark isolation and quantile reporting without external services."""

import pytest

from evals.run_load import percentile, validate_target


def test_load_target_requires_private_local_database_and_redis():
    mysql = "mysql+pymysql://example@127.0.0.1/citymate_load_012345abcdef"
    redis = "redis://127.0.0.1:16379/15"
    assert validate_target(mysql, redis) == "012345abcdef"
    for database, cache in [
        (mysql.replace("citymate_load_012345abcdef", "citymate"), redis),
        (mysql.replace("127.0.0.1", "remote.example"), redis),
        (mysql, redis.replace("/15", "/0")),
        (mysql, redis.replace("127.0.0.1", "remote.example")),
    ]:
        with pytest.raises(ValueError):
            validate_target(database, cache)


def test_nearest_rank_percentiles_do_not_hide_small_sample_extremes():
    assert percentile([], 0.95) is None
    assert percentile(list(range(1, 101)), 0.95) == 95
    assert percentile([10, 1, 2, 3, 4, 5], 0.95) == 10
