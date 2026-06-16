from flask import Flask, render_template, request, jsonify
import ee
import json
import os

app = Flask(__name__, static_folder='static', template_folder='templates')

# Inicijalizacija GEE
def init_gee():
    key_path = 'ee-vubulatovic-26e58a89705c.json'
    if os.path.exists(key_path):
        # Lokalno - koristi JSON fajl
        service_account = 'prokuplje-uhi-sa@ee-vubulatovic.iam.gserviceaccount.com'
        credentials = ee.ServiceAccountCredentials(service_account, key_path)
    else:
        # Render - koristi environment variable
        key_json = os.environ.get('EE_PRIVATE_KEY', '{}')
        service_account = os.environ.get('EE_SERVICE_ACCOUNT')
        credentials = ee.ServiceAccountCredentials(service_account, key_data=key_json)
    
    ee.Initialize(credentials, project='ee-vubulatovic')

init_gee()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data       = request.json
    start_date = data.get('start', '2025-06-01')
    end_date   = data.get('end',   '2025-08-31')
    cloud_pct  = data.get('cloud', 30)

    try:
        aoi        = ee.FeatureCollection('projects/ee-vubulatovic/assets/Prokuplje')
        sva_naselja = ee.FeatureCollection('projects/ee-vubulatovic/assets/NaseljaJug')
        prokuplje  = sva_naselja.filter(ee.Filter.eq('NAME', 'Prokuplje'))
        buffer     = prokuplje.geometry().buffer(500)

        def mask_clouds(img):
            qa = img.select('QA_PIXEL')
            return img.updateMask(
                qa.bitwiseAnd(1 << 3).eq(0)
                .And(qa.bitwiseAnd(1 << 4).eq(0))
                .And(qa.bitwiseAnd(1 << 2).eq(0))
            )

        def scale_sr(img):
            opt = img.select(['SR_B2','SR_B3','SR_B4','SR_B5','SR_B6','SR_B7']) \
                     .multiply(0.0000275).add(-0.2)
            return img.addBands(opt, None, True)

        def add_ndvi(img):
            return img.addBands(
                img.normalizedDifference(['SR_B5','SR_B4']).rename('NDVI')
            )

        def add_lst(img):
            return img.addBands(
                img.select('ST_B10').multiply(0.00341802).add(149.0)
                   .subtract(273.15).rename('LST')
            )

        landsat = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
            .merge(ee.ImageCollection('LANDSAT/LC09/C02/T1_L2'))
            .filterBounds(aoi)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.lt('CLOUD_COVER', cloud_pct)))

        processed = (landsat
            .map(mask_clouds)
            .map(scale_sr)
            .map(add_ndvi)
            .map(add_lst)
            .sort('system:time_start'))

        urban_mask = ee.Image.constant(1).clip(prokuplje).mask()
        rural_mask = ee.Image.constant(1).clip(aoi).mask().And(urban_mask.Not())

        mean_lst      = processed.select('LST').median().clip(prokuplje)
        mean_lst_full = processed.select('LST').median().clip(aoi)

        rural_temp = ee.Number(
            mean_lst_full.updateMask(rural_mask).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=aoi,
                scale=100,
                maxPixels=1e13
            ).get('LST')
        )
        rural_temp = ee.Number(ee.Algorithms.If(rural_temp, rural_temp, ee.Number(25)))

        uhi = mean_lst.subtract(rural_temp).rename('UHI')

        stats_dict = uhi.updateMask(urban_mask).reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), None, True),
            geometry=prokuplje.geometry(),
            scale=30,
            maxPixels=1e13
        )

        mean_uhi = ee.Number(ee.Algorithms.If(stats_dict.get('UHI_mean'),   stats_dict.get('UHI_mean'),   ee.Number(0)))
        std_uhi  = ee.Number(ee.Algorithms.If(stats_dict.get('UHI_stdDev'), stats_dict.get('UHI_stdDev'), ee.Number(1)))

        uhi_z = uhi.subtract(mean_uhi).divide(std_uhi)

        urban_class = (ee.Image(0)
            .where(uhi_z.lt(-1.5), 1)
            .where(uhi_z.gte(-1.5).And(uhi_z.lt(-0.5)), 2)
            .where(uhi_z.gte(-0.5).And(uhi_z.lt(0.5)),  3)
            .where(uhi_z.gte(0.5).And(uhi_z.lt(1.5)),   4)
            .where(uhi_z.gte(1.5).And(uhi_z.lt(2.5)),   5)
            .where(uhi_z.gte(2.5).And(uhi_z.lt(3.5)),   6)
            .where(uhi_z.gte(3.5), 7)
            .updateMask(urban_mask))

        colors = ['#313695','#74add1','#abd9e9','#ffffbf','#fdae61','#f46d43','#a50026']
        zone_labels = ['Hladne zone','Hladnije urbano','Neutralno',
                       'Umereno toplo','Toplo','Jako toplo','Ekstremno jezgro']

        # Tile URL-ovi za slojeve
        def get_tile_url(image, vis_params):
            map_id = image.getMapId(vis_params)
            return map_id['tile_fetcher'].url_format

        lst_url = get_tile_url(mean_lst, {
            'min': 20, 'max': 45,
            'palette': ['blue','cyan','green','yellow','orange','red']
        })

        ndvi_mean = processed.select('NDVI').median().clip(prokuplje)
        ndvi_url  = get_tile_url(ndvi_mean, {
            'min': 0, 'max': 1,
            'palette': ['brown','yellow','green']
        })

        uhi_url = get_tile_url(uhi, {
            'min': -2, 'max': 10,
            'palette': ['blue','cyan','white','yellow','orange','red']
        })

        zones_url = get_tile_url(urban_class, {
            'min': 1, 'max': 7,
            'palette': colors
        })

        # Statistike po zonama
        zone_stats = []
        for z in range(1, 8):
            zone_mask = urban_class.eq(z)
            stats = ee.Dictionary({
                'area': zone_mask.multiply(ee.Image.pixelArea()).reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=prokuplje.geometry(),
                    scale=30,
                    maxPixels=1e13
                ).get('constant'),
                'lst': mean_lst.updateMask(zone_mask).reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=prokuplje.geometry(),
                    scale=30,
                    maxPixels=1e13
                ).get('LST')
            }).getInfo()

            if stats and stats.get('area') and stats['area'] > 0:
                zone_stats.append({
                    'zone':  z,
                    'label': zone_labels[z - 1],
                    'color': colors[z - 1],
                    'area':  round(stats['area'] / 10000, 2),
                    'lst':   round(stats['lst'], 1) if stats.get('lst') else None
                })

        return jsonify({
            'success':   True,
            'tiles': {
                'lst':   lst_url,
                'ndvi':  ndvi_url,
                'uhi':   uhi_url,
                'zones': zones_url
            },
            'zone_stats': zone_stats
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    app.run(debug=True)
@app.route('/lst_series', methods=['POST'])
def lst_series():
    data = request.json
    lat  = data.get('lat')
    lon  = data.get('lon')

    try:
        aoi        = ee.FeatureCollection('projects/ee-vubulatovic/assets/Prokuplje')
        sva_naselja = ee.FeatureCollection('projects/ee-vubulatovic/assets/NaseljaJug')
        prokuplje  = sva_naselja.filter(ee.Filter.eq('NAME', 'Prokuplje'))

        landsat = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
            .merge(ee.ImageCollection('LANDSAT/LC09/C02/T1_L2'))
            .filterBounds(prokuplje)
            .filterDate('2020-01-01', '2025-12-31')
            .filter(ee.Filter.lt('CLOUD_COVER', 30)))

        def mask_clouds(img):
            qa = img.select('QA_PIXEL')
            return img.updateMask(
                qa.bitwiseAnd(1 << 3).eq(0)
                .And(qa.bitwiseAnd(1 << 4).eq(0))
                .And(qa.bitwiseAnd(1 << 2).eq(0))
            )

        def add_lst(img):
            return img.addBands(
                img.select('ST_B10').multiply(0.00341802).add(149.0)
                   .subtract(273.15).rename('LST')
            )

        processed = landsat.map(mask_clouds).map(add_lst).sort('system:time_start')

        point = ee.Geometry.Point(lon, lat)

        values = processed.select('LST').getRegion(point, 30).getInfo()

        # Prva linija su headeri, ostalo su podaci
        headers = values[0]
        rows    = values[1:]
        date_idx = headers.index('time')
        lst_idx  = headers.index('LST')

        dates  = []
        lst_vals = []

        for row in rows:
            if row[lst_idx] is not None:
                import datetime
                ts   = row[date_idx] / 1000
                date = datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
                dates.append(date)
                lst_vals.append(round(row[lst_idx], 1))

        return jsonify({ 'success': True, 'dates': dates, 'values': lst_vals })

    except Exception as e:
        return jsonify({ 'success': False, 'error': str(e) })