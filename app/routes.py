import os
import io
import re
import json
import csv
import pandas as pd
from flask import Blueprint, render_template, request, jsonify
import folium
from folium.plugins import MousePosition, MeasureControl

main = Blueprint("main", __name__)

CENTER = [-34.5, -73.0]
ZOOM = 7
MINZOOM = 5
MAXZOOM = 14

COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9a6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
]

AMP_CONFIG = [
    {
        "nombre": "Areas Protegidas Chile",
        "layer": "areasprotegidas:areasprotegidaschile", "show": True,
        "fields": {"nombre": ["nombre_ap"], "region": ["region"], "designacion": ["designacion_ap"], "area": ["ha"], "areaUnit": "ha", "pais": "Chile"},
        "color": "#356EF2",
    },
    {
        "nombre": "Areas Protegidas Peru",
        "layer": "areasprotegidas:areasprotegidasperu", "show": False,
        "fields": {"nombre": ["anp_nomb"], "region": ["anp_uicn"], "designacion": ["anp_cate"], "area": ["anp_suleg"], "areaUnit": "ha", "pais": "Peru"},
        "color": "#F2AD35",
    },
    {
        "nombre": "Areas Protegidas Argentina",
        "layer": "areasprotegidas:areasprotegidasargentina", "show": False,
        "fields": {"nombre": ["NAME"], "region": ["DESIG_TYPE"], "designacion": ["DESIG"], "area": ["REP_AREA"], "areaUnit": "km2", "pais": "Argentina"},
        "color": "#87CEEB",
    },
]


def detect_lat_lon_columns(df):
    """Detecta columnas de latitud y longitud en un DataFrame."""
    lat_col = None
    lon_col = None
    for col in df.columns:
        col_lower = col.lower().strip()
        if col_lower in ("lat", "latitude", "latitud", "latitud_y", "y"):
            lat_col = col
        elif col_lower in ("lon", "long", "longitude", "longitud", "longitud_x", "lng", "x"):
            lon_col = col
    return lat_col, lon_col


def parse_coordinates(file_path, filename):
    """Lee archivo Excel o CSV y extrae coordenadas lat/lon."""
    ext = filename.lower().rsplit(".", 1)[-1]

    df = None
    sheet_name = None

    try:
        if ext == "csv":
            # Intentar con diferentes separadores
            for sep in [",", ";", "\t", "|"]:
                try:
                    df = pd.read_csv(file_path, sep=sep, encoding="utf-8")
                    if len(df.columns) > 1:
                        break
                except Exception:
                    continue
            if df is None or len(df.columns) < 2:
                # Intentar con encoding latino
                for sep in [",", ";", "\t", "|"]:
                    try:
                        df = pd.read_csv(file_path, sep=sep, encoding="latin-1")
                        if len(df.columns) > 1:
                            break
                    except Exception:
                        continue
            if df is None:
                return None, "No se pudo leer el archivo CSV. Verifica que use comas, punto y coma o tabulador como separador."
        else:
            # Excel - probar todas las hojas
            xls = pd.ExcelFile(file_path, engine="openpyxl")
            for sheet in xls.sheet_names:
                try:
                    temp_df = pd.read_excel(file_path, sheet_name=sheet, engine="openpyxl")
                    lat_c, lon_c = detect_lat_lon_columns(temp_df)
                    if lat_c and lon_c:
                        df = temp_df
                        sheet_name = sheet
                        break
                except Exception:
                    continue
            if df is None:
                return None, (
                    "El archivo Excel no contiene columnas de coordenadas reconocibles en ninguna hoja.\n\n"
                    "El sistema busca columnas con nombres como: lat, latitud, latitude, lon, longitud, longitude, lng\n\n"
                    "Ejemplo de formato esperado:\n"
                    "| latitud | longitud | nombre_punto |\n"
                    "|---------|----------|-------------|\n"
                    "| -33.45  | -71.61   | Estacion 1  |\n"
                    "| -34.12  | -72.85   | Estacion 2  |"
                )
    except Exception as e:
        return None, f"Error al leer el archivo: {str(e)}"

    if df is None or df.empty:
        return None, "El archivo no contiene datos."

    lat_col, lon_col = detect_lat_lon_columns(df)
    if not lat_col or not lon_col:
        cols_encontradas = ", ".join(df.columns.tolist())
        return None, (
            f"No se encontraron columnas de latitud/longitud.\n\n"
            f"Columnas encontradas: {cols_encontradas}\n\n"
            "Se requieren columnas con nombres como: lat, latitud, latitude, lon, longitud, longitude, lng\n\n"
            "Ejemplo de formato esperado:\n"
            "| lat | lon |\n"
            "|-----|-----|\n"
            "| -33.45 | -71.61 |\n"
            "| -34.12 | -72.85 |"
        )

    # Extraer coordenadas
    puntos = []
    errores = []
    for idx, row in df.iterrows():
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
            if lat < -90 or lat > 90:
                errores.append(f"Fila {idx+2}: latitud {lat} fuera de rango (-90 a 90)")
                continue
            if lon < -180 or lon > 180:
                errores.append(f"Fila {idx+2}: longitud {lon} fuera de rango (-180 a 180)")
                continue
            puntos.append([lat, lon])
        except (ValueError, TypeError):
            errores.append(f"Fila {idx+2}: valor no numerico en latitud '{row[lat_col]}' o longitud '{row[lon_col]}'")

    if errores:
        error_msg = "\n".join(errores[:10])
        if len(errores) > 10:
            error_msg += f"\n... y {len(errores)-10} errores mas"
        return None, f"Se encontraron errores en los datos:\n{error_msg}"

    if not puntos:
        return None, "No se pudieron extraer coordenadas validas del archivo."

    # Ordenar de norte a sur
    puntos.sort(key=lambda p: p[0], reverse=True)

    info_adicional = f"Hoja: {sheet_name}" if sheet_name else ""
    return puntos, info_adicional


@main.route("/")
def index():
    return render_template("tracker.html", mapa_html=None, filename=None, info=None)


@main.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No se encontro el archivo. Arrastra o selecciona un archivo para subir."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No se selecciono ningun archivo."}), 400

    ext = file.filename.lower().rsplit(".", 1)[-1]
    if ext not in ("xlsx", "xls", "csv"):
        return jsonify({
            "error": (
                "Formato de archivo no soportado. Solo se aceptan:\n"
                "• Excel (.xlsx, .xls)\n"
                "• CSV (.csv)\n\n"
                "El archivo debe contener columnas de latitud y longitud."
            )
        }), 400

    try:
        file.seek(0)
        file_bytes = file.read()
        file_path = f"/tmp/{file.filename}"
        with open(file_path, "wb") as f:
            f.write(file_bytes)
    except Exception as e:
        return jsonify({"error": f"Error al guardar el archivo: {str(e)}"}), 400

    puntos, info_adicional = parse_coordinates(file_path, file.filename)
    if puntos is None:
        return jsonify({"error": info_adicional}), 400

    try:
        mapa_html = generate_map(puntos)
        info = {"puntos": len(puntos), "info": info_adicional}
        return jsonify({"map": mapa_html, "filename": file.filename, "info": info})
    except Exception as e:
        return jsonify({"error": f"Error al generar el mapa: {str(e)}"}), 500


def generate_map(puntos):
    m = folium.Map(
        location=CENTER,
        zoom_start=ZOOM,
        tiles=None,
        minZoom=MINZOOM,
        maxZoom=MAXZOOM,
        zoomSnap=1,
        zoomDelta=1,
    )

    # Capa base
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Calle", control=False
    ).add_to(m)

    # Plugins
    MeasureControl(
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
    ).add_to(m)

    MousePosition(
        position="bottomleft",
        separator=" | ",
        prefix="Coordenadas:",
        num_digits=5,
    ).add_to(m)

    # Areas Protegidas (WMS desde GeoServer)
    for capa in AMP_CONFIG:
        grupo = folium.FeatureGroup(name=capa["nombre"], show=capa["show"])
        folium.WmsTileLayer(
            url="https://gis-eco.ifop.cl/geoserver/areasprotegidas/wms?",
            layers=capa["layer"],
            fmt="image/png",
            transparent=True,
            version="1.1.0",
            opacity=0.8,
            overlay=True,
            control=True,
            name=capa["nombre"],
        ).add_to(grupo)
        grupo.add_to(m)

    # Batimetria (deshabilitada por defecto)
    batimetria = folium.FeatureGroup(name="Batimetria", show=False)
    folium.WmsTileLayer(
        url="https://gis-eco.ifop.cl/geoserver/Ifop_Sapo/wms?",
        layers="Ifop_Sapo:Profundidad",
        styles="4_profundidad",
        fmt="image/png",
        transparent=True,
        version="1.1.0",
        opacity=1.0,
        overlay=True,
        control=True,
        name="Batimetria",
    ).add_to(batimetria)
    batimetria.add_to(m)

    # Puntos del track
    for pt in puntos:
        folium.CircleMarker(
            pt,
            radius=4,
            color="#e6194b",
            fill=True,
            fillColor="#e6194b",
            fillOpacity=0.8,
            weight=1,
            popup=f"({pt[0]:.4f}, {pt[1]:.4f})",
        ).add_to(m)

    # Layer control
    folium.LayerControl(collapsed=False).add_to(m)

    # Ajustar vista a los datos
    all_lats = [pt[0] for pt in puntos]
    all_lons = [pt[1] for pt in puntos]
    m.fit_bounds(
        [[min(all_lats) - 0.5, min(all_lons) - 0.5],
         [max(all_lats) + 0.5, max(all_lons) + 0.5]],
        max_zoom=10,
    )

    # Generar HTML
    data = io.BytesIO()
    m.save(data, close_file=False)
    mapa_html = data.getvalue().decode()

    # Mover styles y scripts
    head_styles = re.findall(r'<style>.*?</style>', mapa_html, re.DOTALL)
    for s in head_styles:
        mapa_html = mapa_html.replace(s, '', 1)
    mapa_html = mapa_html.replace('</body>', '', 1)
    body_extra = ''.join(head_styles)
    mapa_html = mapa_html.replace('</html>', body_extra + '</body></html>')

    # Script AMP
    custom_script = _build_amp_script()
    mapa_html = mapa_html.replace('</body>', custom_script + '</body>')

    return mapa_html


def _build_amp_script():
    layer_defs = []
    for capa in AMP_CONFIG:
        layer_defs.append(
            '{"layer":"%s","color":"%s","fields":%s}'
            % (capa["layer"], capa["color"], json.dumps(capa["fields"], ensure_ascii=False))
        )

    script = """
    <script>
    var ampLayers = [%s];

    function getFieldValue(props, candidates) {
        for (var i = 0; i < candidates.length; i++) {
            if (props.hasOwnProperty(candidates[i])) return props[candidates[i]];
            for (var key in props) {
                if (key.toLowerCase() === candidates[i].toLowerCase()) return props[key];
            }
        }
        return "";
    }

    function formatArea(value, unit) {
        if (!value) return "N/D";
        var num = unit === "km2" ? parseFloat(value) : parseFloat(value) / 100;
        return num.toLocaleString("es-ES", {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }

    function clickAMP(e, index) {
        if (index === undefined) index = 0;
        if (index >= ampLayers.length) return;
        var layerDef = ampLayers[index];
        var point = e.latlng;
        var map = e.target;
        var size = map.getSize();
        var sw = L.CRS.EPSG3857.project(map.getBounds().getSouthWest());
        var ne = L.CRS.EPSG3857.project(map.getBounds().getNorthEast());
        var cp = map.latLngToContainerPoint(point);
        var url = "https://gis-eco.ifop.cl/geoserver/areasprotegidas/wms?" +
            "SERVICE=WMS&VERSION=1.1.1&REQUEST=GetFeatureInfo" +
            "&QUERY_LAYERS=" + layerDef.layer +
            "&LAYERS=" + layerDef.layer +
            "&INFO_FORMAT=application/json&FEATURE_COUNT=5" +
            "&X=" + Math.round(cp.x) + "&Y=" + Math.round(cp.y) +
            "&SRS=EPSG:3857&WIDTH=" + size.x + "&HEIGHT=" + size.y +
            "&BBOX=" + sw.x + "," + sw.y + "," + ne.x + "," + ne.y;
        fetch(url).then(function(r) { return r.json(); }).then(function(data) {
            if (data.features && data.features.length > 0) {
                var f = data.features[0], props = f.properties, fields = layerDef.fields;
                var nombre = getFieldValue(props, fields.nombre) || "S/N";
                var region = getFieldValue(props, fields.region) || "";
                var designacion = getFieldValue(props, fields.designacion) || "";
                var areaKm2 = formatArea(getFieldValue(props, fields.area), fields.areaUnit);
                var content = '<div style="font-size:12px;font-family:Inter,sans-serif;">' +
                    "<strong>Nombre:</strong> " + nombre + "<br>" +
                    "<strong>Pais:</strong> " + (fields.pais || "") + "<br>" +
                    "<strong>Designacion:</strong> " + designacion + "<br>" +
                    "<strong>Area:</strong> " + areaKm2 + " km\\u00b2</div>";
                L.popup().setLatLng(point).setContent(content).openOn(map);
            } else { clickAMP(e, index + 1); }
        }).catch(function() { clickAMP(e, index + 1); });
    }

    (function() {
        function initAMP() {
            for (var key in window) {
                if (key.startsWith("map_")) {
                    var map = window[key];
                    if (map && map.on) {
                        map.on("click", function(e) { clickAMP(e); });
                        return;
                    }
                }
            }
            setTimeout(initAMP, 500);
        }
        initAMP();
    })();
    </script>
    """ % ",".join(layer_defs)
    return script
