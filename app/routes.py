import os
import io
import re
import json
from flask import Blueprint, render_template, request, jsonify
import folium
from folium.plugins import MousePosition, MeasureControl
import openpyxl

main = Blueprint("main", __name__)

# Configuracion del mapa
CENTER = [-34.5, -73.0]
ZOOM = 7
MINZOOM = 5
MAXZOOM = 14

# Colores para tracks UBM
COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9a6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
]

AMP_CONFIG = [
    {
        "nombre": "Areas Protegidas Chile",
        "layer": "areasprotegidas:areasprotegidaschile",
        "show": True,
        "fields": {
            "nombre": ["nombre_ap"],
            "region": ["region"],
            "designacion": ["designacion_ap"],
            "area": ["ha"],
            "areaUnit": "ha",
            "pais": "Chile",
        },
        "color": "#356EF2",
    },
    {
        "nombre": "Areas Protegidas Peru",
        "layer": "areasprotegidas:areasprotegidasperu",
        "show": False,
        "fields": {
            "nombre": ["anp_nomb"],
            "region": ["anp_uicn"],
            "designacion": ["anp_cate"],
            "area": ["anp_suleg"],
            "areaUnit": "ha",
            "pais": "Peru",
        },
        "color": "#F2AD35",
    },
    {
        "nombre": "Areas Protegidas Argentina",
        "layer": "areasprotegidas:areasprotegidasargentina",
        "show": False,
        "fields": {
            "nombre": ["NAME"],
            "region": ["DESIG_TYPE"],
            "designacion": ["DESIG"],
            "area": ["REP_AREA"],
            "areaUnit": "km2",
            "pais": "Argentina",
        },
        "color": "#87CEEB",
    },
]


@main.route("/")
def index():
    return render_template("tracker.html", mapa_html=None, filename=None, info=None)


@main.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No se encontro el archivo"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No se selecciono ningun archivo"}), 400

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"error": "Solo se aceptan archivos Excel (.xlsx)"}), 400

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file.read()))
    except Exception as e:
        return jsonify({"error": f"Error al leer el archivo Excel: {str(e)}"}), 400

    tracks_data = []

    # Leer hoja "Transectas Dia" (tracks diarios)
    if "Transectas Dia" not in wb.sheetnames:
        return jsonify({"error": "El archivo debe contener una hoja llamada 'Transectas Dia'"}), 400

    ws = wb["Transectas Dia"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) >= 2 and row[0] is not None and row[1] is not None:
            try:
                lon = float(row[0])
                lat = float(row[1])
                tracks_data.append([lat, lon])
            except (ValueError, TypeError):
                continue

    if not tracks_data:
        return jsonify({"error": "No se encontraron datos en la hoja 'Transectas Dia'"}), 400

    # Ordenar puntos de norte a sur (lat descendente)
    tracks_data.sort(key=lambda p: p[0], reverse=True)

    try:
        mapa_html = generate_map(tracks_data)
        info = {"puntos": len(tracks_data)}
        return jsonify({"map": mapa_html, "filename": file.filename, "info": info})
    except Exception as e:
        return jsonify({"error": f"Error al generar el mapa: {str(e)}"}), 500


def generate_map(tracks_data):
    m = folium.Map(
        location=CENTER,
        zoom_start=ZOOM,
        tiles=None,
        minZoom=MINZOOM,
        maxZoom=MAXZOOM,
        zoomDelta=0.15,
        zoomSnap=0.15,
        wheelPxPerZoomLevel=250,
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

    # Puntos del track
    for pt in tracks_data:
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
    all_lats = [pt[0] for pt in tracks_data] if tracks_data else [CENTER[0]]
    all_lons = [pt[1] for pt in tracks_data] if tracks_data else [CENTER[1]]

    m.fit_bounds(
        [[min(all_lats) - 0.5, min(all_lons) - 0.5],
         [max(all_lats) + 0.5, max(all_lons) + 0.5]],
        max_zoom=10,
    )

    # Generar HTML completo de Folium
    data = io.BytesIO()
    m.save(data, close_file=False)
    mapa_html = data.getvalue().decode()

    # El frontend extrae solo doc.body.innerHTML, que pierde:
    # 1. Los <style> del <head> (dimensiones del mapa, etc.)
    # 2. Los scripts que Folium pone despues de </body>
    # Solucion: mover todo al <body>

    # Extraer <style> blocks del <head> y removerlos de ahi
    head_styles = re.findall(r'<style>.*?</style>', mapa_html, re.DOTALL)
    for s in head_styles:
        mapa_html = mapa_html.replace(s, '', 1)

    # Mover scripts de despues de </body> a dentro del body
    mapa_html = mapa_html.replace('</body>', '', 1)

    # Insertar styles + cierre body antes de </html>
    body_extra = ''.join(head_styles)
    mapa_html = mapa_html.replace('</html>', body_extra + '</body></html>')

    # Agregar script AMP justo antes de </body>
    custom_script = _build_amp_script()
    mapa_html = mapa_html.replace('</body>', custom_script + '</body>')

    return mapa_html


def _build_amp_script():
    """Build the JavaScript for AMP click interaction via WMS GetFeatureInfo."""
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
