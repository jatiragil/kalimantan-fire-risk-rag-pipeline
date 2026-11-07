{{ config(materialized='table') }}

WITH base AS (
    SELECT
        city_name,
        observation_date,
        temperature_max,
        precipitation_sum,
        wind_speed_max,
        relative_humidity_mean,
        data_source,
        
        -- Rata-rata 7 hari terakhir (Historical)
        AVG(temperature_max) OVER (
            PARTITION BY city_name 
            ORDER BY observation_date 
            RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 day' PRECEDING
        ) AS avg_temp_7d,
        AVG(precipitation_sum) OVER (
            PARTITION BY city_name 
            ORDER BY observation_date 
            RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 day' PRECEDING
        ) AS avg_rain_7d,
        AVG(wind_speed_max) OVER (
            PARTITION BY city_name 
            ORDER BY observation_date 
            RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 day' PRECEDING
        ) AS avg_wind_7d,
        AVG(relative_humidity_mean) OVER (
            PARTITION BY city_name 
            ORDER BY observation_date 
            RANGE BETWEEN INTERVAL '7 days' PRECEDING AND INTERVAL '1 day' PRECEDING
        ) AS avg_rh_7d,

        -- Rata-rata 3 hari ke depan (Forecast)
        AVG(temperature_max) OVER (
            PARTITION BY city_name 
            ORDER BY observation_date 
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING AND INTERVAL '3 days' FOLLOWING
        ) AS avg_temp_forecast_3d,
        AVG(precipitation_sum) OVER (
            PARTITION BY city_name 
            ORDER BY observation_date 
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING AND INTERVAL '3 days' FOLLOWING
        ) AS avg_rain_forecast_3d,
        AVG(wind_speed_max) OVER (
            PARTITION BY city_name 
            ORDER BY observation_date 
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING AND INTERVAL '3 days' FOLLOWING
        ) AS avg_wind_forecast_3d,
        AVG(relative_humidity_mean) OVER (
            PARTITION BY city_name 
            ORDER BY observation_date 
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING AND INTERVAL '3 days' FOLLOWING
        ) AS avg_rh_forecast_3d
    FROM {{ ref('stg_weather') }}
)

SELECT
    city_name,
    observation_date,
    data_source,
    avg_temp_7d,
    avg_rain_7d,
    avg_wind_7d,
    avg_rh_7d,
    avg_temp_forecast_3d,
    avg_rain_forecast_3d,
    avg_wind_forecast_3d,
    avg_rh_forecast_3d,
    
    -- Logika Risiko Historis (5 Level - Menggunakan rata-rata 7 hari konsisten)
    CASE 
        WHEN avg_temp_7d IS NULL OR avg_rain_7d IS NULL THEN 'TIDAK DIKETAHUI'
        WHEN avg_temp_7d > 33 AND avg_rain_7d < 20 AND avg_wind_7d > 14 AND avg_rh_7d < 50 THEN 'EKSTREM'
        WHEN avg_temp_7d > 33 AND avg_rain_7d < 20 AND (avg_wind_7d > 14 OR avg_rh_7d < 50) THEN 'AWAS'
        WHEN avg_temp_7d > 33 AND avg_rain_7d < 20 THEN 'SIAGA'
        WHEN avg_temp_7d > 32 AND avg_rain_7d < 50 THEN 'WASPADA'
        ELSE 'AMAN'
    END AS risk_status_historical,
    
    -- Logika Risiko Forecast (5 Level - Menggunakan rata-rata 3 hari)
    CASE 
        WHEN avg_temp_forecast_3d IS NULL OR avg_rain_forecast_3d IS NULL THEN 'TIDAK DIKETAHUI'
        WHEN avg_temp_forecast_3d > 33 AND avg_rain_forecast_3d < 20 AND avg_wind_forecast_3d > 14 AND avg_rh_forecast_3d < 50 THEN 'EKSTREM'
        WHEN avg_temp_forecast_3d > 33 AND avg_rain_forecast_3d < 20 AND (avg_wind_forecast_3d > 14 OR avg_rh_forecast_3d < 50) THEN 'AWAS'
        WHEN avg_temp_forecast_3d > 33 AND avg_rain_forecast_3d < 20 THEN 'SIAGA'
        WHEN avg_temp_forecast_3d > 32 AND avg_rain_forecast_3d < 50 THEN 'WASPADA'
        ELSE 'AMAN'
    END AS risk_status_forecast
FROM base
WHERE avg_temp_7d IS NOT NULL
