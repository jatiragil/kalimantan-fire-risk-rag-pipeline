{{ config(materialized='table') }}

SELECT
    city_name,
    EXTRACT(MONTH FROM observation_date) AS month,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY precipitation_sum) AS p95_rain
FROM {{ ref('stg_weather') }}
GROUP BY city_name, EXTRACT(MONTH FROM observation_date)
HAVING COUNT(*) >= 30
