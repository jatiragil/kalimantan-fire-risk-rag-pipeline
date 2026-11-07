{{ config(materialized='table') }}

WITH daily_stats AS (
    SELECT
        city_name,
        observation_date,
        temperature_max,
        precipitation_sum,
        AVG(temperature_max) OVER w AS rolling_avg_temp,
        STDDEV(temperature_max) OVER w AS rolling_std_temp,
        ROW_NUMBER() OVER (
            PARTITION BY city_name ORDER BY observation_date
        ) AS row_num
    FROM {{ ref('stg_weather') }}
    WINDOW w AS (
        PARTITION BY city_name
        ORDER BY observation_date
        RANGE BETWEEN INTERVAL '30 days' PRECEDING
                  AND INTERVAL '1 day' PRECEDING
    )
)

SELECT
    city_name,
    observation_date,
    temperature_max,
    precipitation_sum,
    rolling_avg_temp,
    rolling_std_temp,
    CASE
        WHEN rolling_std_temp > 0
        THEN (temperature_max - rolling_avg_temp) / rolling_std_temp
        ELSE 0.0
    END AS z_score,
    CASE
        WHEN rolling_std_temp > 0
         AND ABS((temperature_max - rolling_avg_temp) / rolling_std_temp)
             > {{ var('anomaly_z_threshold', 3.0) }}
        THEN TRUE ELSE FALSE
    END AS is_extreme_temperature,
    (row_num <= 30) AS is_warmup
FROM daily_stats
