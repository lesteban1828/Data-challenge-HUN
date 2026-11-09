# Dashboard Power BI

**Proyecto listo: `HUN_Flujo.pbip`** (formato de proyecto de Power BI: modelo TMDL + reporte PBIR, todo en texto).
Se genera con `python scripts/build_powerbi.py`, que además escribe las tablas en `D:/HUN_DataChallenge_datos/powerbi/`
y el tema glass (`tema_HUN_glass.json`, ya aplicado dentro del reporte).

1. Abrir `HUN_Flujo.pbip` con Power BI Desktop.
2. **Actualizar** (barra amarilla o Inicio → Actualizar) para cargar los datos.
3. Para entregar: *Archivo → Guardar como* `.pbix` y *Publicar* en el servicio de Power BI con la cuenta Uninorte.

Si cambia la carpeta de datos, editar el parámetro `Ruta` (Transformar datos → Parámetros).
Las secciones de abajo describen el diseño original; el proyecto generado sigue esa estructura.

## Modelo de datos (estrella)

```
dim_fecha (fecha) ──1:N── fact_episodio (fecha, episodio_id) ──1:N── fact_etapa (episodio_id)
dim_diagnostico (dx_principal) ──1:N── fact_episodio (dx_principal)

Tablas sueltas: fact_ocupacion_horaria, transiciones, variantes, shap_importancia,
perfil_dx, pronostico, escenarios
```

| Tabla | Grano | Uso |
|---|---|---|
| fact_episodio | 1 fila por episodio de urgencias (694 509) | KPIs, filtros por tipo, edad, franja, diagnóstico |
| fact_etapa | 1 fila por etapa (1,57 M) | duración por etapa, esperas entre etapas |
| fact_ocupacion_horaria | 1 fila por hora | heatmap y tendencia de ocupación |
| pronostico | últimos 120 días | real vs. pronóstico, probabilidad de saturación |
| escenarios | 1 fila por escenario | página de recomendaciones |

Filtro recomendado en todas las páginas: `fact_episodio[los_atipica] = 0` (excluye 1,5 % de estancias sin cierre).

## Páginas

1. **Resumen ejecutivo**: episodios/día, pacientes, % hospitalizados, mediana de espera de cama, tendencia mensual.
2. **Flujo y cuellos de botella**: Sankey `etapa_anterior → etapa` (visual "Sankey Chart" de AppSource, valor = `n` de `transiciones`), composición por `tipo_detalle`, distribución de `h_hasta_hosp`.
3. **Congestión**: heatmap hora × día (`fact_ocupacion_horaria`), pico diario vs. umbral P90.
4. **Factores de demora**: barras de `shap_importancia` (filtrar por `modelo`), `perfil_dx`.
5. **Predicción y alerta**: línea real vs. pronóstico, semáforo con `prob_saturacion`.
6. **Recomendaciones**: tabla de `escenarios` con el cambio % en la espera de cama.

## Medidas DAX

```DAX
Episodios = COUNTROWS ( fact_episodio )
Pacientes = DISTINCTCOUNT ( fact_episodio[person_id] )
Episodios por día = DIVIDE ( [Episodios], DISTINCTCOUNT ( fact_episodio[fecha] ) )
% Hospitalizados = DIVIDE ( CALCULATE ( [Episodios], fact_episodio[hospitalizado] = TRUE () ), [Episodios] )

Estancia mediana (h) = MEDIAN ( fact_episodio[los_h] )
Estancia P90 (h) = PERCENTILEX.INC ( fact_episodio, fact_episodio[los_h], 0.9 )

Espera de cama mediana (h) =
    CALCULATE ( MEDIAN ( fact_episodio[h_hasta_hosp] ),
                fact_episodio[tipo_detalle] = "Urgencias → Hospitalización" )
Espera de cama P90 (h) =
    CALCULATE ( PERCENTILEX.INC ( fact_episodio, fact_episodio[h_hasta_hosp], 0.9 ),
                fact_episodio[tipo_detalle] = "Urgencias → Hospitalización" )

% Reconsulta 72h = AVERAGE ( fact_episodio[reconsulta_72h] )
Ocupación pico = MAX ( fact_ocupacion_horaria[ocupacion] )

Riesgo saturación =
VAR p = MAX ( pronostico[prob_saturacion] )
RETURN SWITCH ( TRUE (), p >= 0.7, "Alto", p >= 0.4, "Medio", "Bajo" )
```

## Publicar

Publicar en Power BI Service (cuenta Uninorte) → "Publicar en la web" o compartir enlace, según lo que pidan los organizadores. **No publicar en la web datos a nivel de paciente**: para un enlace público usar solo tablas agregadas.
