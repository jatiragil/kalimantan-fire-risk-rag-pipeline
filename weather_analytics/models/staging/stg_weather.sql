{{ config(materialized='view') }}

SELECT
    city_name,
    observation_date,
    temperature_max,
    precipitation_sum,
    wind_speed_max,
    relative_humidity_mean,
    data_source,
    ingested_at
FROM {{ source('raw', 'raw_weather') }}
