import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import httpx
from shapely.geometry import MultiPolygon, Polygon, box, shape

from apps.scripts.brazilgeo import generate as brazilgeo


STATE_CODES = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",

    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",

    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",

    "41": "PR",
    "42": "SC",
    "43": "RS",

    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}


class BrazilGeoTest(unittest.TestCase):
    def make_source(self, directory: Path) -> tuple[gpd.GeoDataFrame, bytes]:
        rows = []
        for index, (code, uf) in enumerate(STATE_CODES.items()):
            longitude = -65 + (index % 9) * 2
            latitude = -25 + (index // 9) * 3
            rows.append({
                "CD_MUN": f"{code}00001",
                "NM_MUN": f"Município {uf}",
                "CD_UF": code,
                "NM_UF": f"Estado {uf}",
                "SIGLA_UF": uf,
                "geometry": box(longitude, latitude, longitude + 1, latitude + 1),
            })

        # Dois municípios contíguos na mesma UF e uma ilha com um buraco.
        rows.append({
            **rows[0],
            "CD_MUN": "1100002",
            "NM_MUN": "São João",
            "geometry": box(-64, -25, -63, -24),
        })
        island = Polygon(
            [(-64.9, -25.5), (-64.5, -25.5), (-64.5, -25.1), (-64.9, -25.1)],
            holes=[[
                (-64.8, -25.4), (-64.6, -25.4), (-64.6, -25.2), (-64.8, -25.2),
            ]],
        )
        rows[0]["geometry"] = MultiPolygon([rows[0]["geometry"], island])
        rows[1]["geometry"] = box(-63.00000001, -25, -62, -24)

        source = gpd.GeoDataFrame(rows, crs="EPSG:4674")
        shapefile = directory / "BR_Municipios_2025.shp"
        source.to_file(shapefile, engine="pyogrio", encoding="UTF-8")

        zip_bytes = io.BytesIO()
        with zipfile.ZipFile(zip_bytes, "w") as archive:
            for path in directory.iterdir():
                archive.write(path, arcname=f"malha/{path.name}")

        return source, zip_bytes.getvalue()

    def test_download_extract_generate_and_replace_maps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source"
            source_dir.mkdir()
            source, zip_bytes = self.make_source(source_dir)

            output_dir = root / "assets" / "brazilgeo"
            output_dir.mkdir(parents=True)
            stale = output_dir / "obsolete.geojson"
            stale.write_text("obsolete")
            sibling = output_dir.parent / "keep.txt"
            sibling.write_text("preserve")

            requests = []

            def respond(request):
                requests.append(str(request.url))
                return httpx.Response(200, content=zip_bytes)

            transport = httpx.MockTransport(respond)
            client = httpx.Client(transport=transport)
            with (
                patch.object(brazilgeo, "OUTPUT_DIR", output_dir),
                patch.object(brazilgeo.httpx, "Client", return_value=client),
                patch("apps.turi.src.infra.downloader.downloader.BASE_DIR", root),
            ):
                brazilgeo.generate()

            self.assertEqual(requests, [brazilgeo.SOURCE_URL])
            self.assertFalse(stale.exists())
            self.assertEqual(sibling.read_text(), "preserve")
            self.assertEqual(len(list(output_dir.rglob("*.geojson"))), 28)
            self.assertEqual(len(list(output_dir.rglob("*.bounds.json"))), 27)

            national = json.loads((output_dir / "BR.geojson").read_text())
            self.assertEqual(national["type"], "FeatureCollection")
            self.assertEqual(len(national["features"]), 27)
            self.assertNotIn("crs", national)
            self.assertEqual(
                {feature["id"] for feature in national["features"]},
                set(STATE_CODES.values()),
            )

            expected = source.to_crs("EPSG:4326").set_index("CD_MUN")
            seen = set()
            for feature in national["features"]:
                properties = feature["properties"]
                self.assertEqual(feature["id"], properties["uf"])
                self.assertTrue(shape(feature["geometry"]).is_valid)
                self.assertEqual(len(properties["municipios_bbox"]), 4)
                state_file = output_dir / properties["municipios_url"]
                state = json.loads(state_file.read_text())
                bounds_file = state_file.with_suffix(".bounds.json")
                bounds = json.loads(bounds_file.read_text())
                self.assertEqual(len(bounds), len(state["features"]))
                self.assertEqual(len(feature["bbox"]), 4)
                self.assertEqual(len(state["bbox"]), 4)

                for municipality in state["features"]:
                    code = municipality["properties"]["codigo_ibge"]
                    self.assertEqual(municipality["id"], code)
                    self.assertEqual(municipality["properties"]["uf"], properties["uf"])
                    self.assertEqual(
                        municipality["properties"]["nome"],
                        expected.loc[code, "NM_MUN"],
                    )

                    geometry = shape(municipality["geometry"])
                    self.assertEqual(bounds[code], list(geometry.bounds))
                    self.assertTrue(geometry.equals(expected.loc[code, "geometry"]))
                    polygons = geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]
                    for polygon in polygons:
                        self.assertTrue(polygon.exterior.is_ccw)
                        self.assertTrue(all(not ring.is_ccw for ring in polygon.interiors))

                    self.assertNotIn(code, seen)
                    seen.add(code)

            self.assertEqual(seen, set(expected.index))

            maps_before = {path: path.read_bytes() for path in output_dir.rglob("*.geojson")}
            for path in output_dir.rglob("*.bounds.json"):
                path.unlink()

            with patch.object(brazilgeo, "OUTPUT_DIR", output_dir):
                brazilgeo.generate_bounds_indexes()

            self.assertEqual(len(list(output_dir.rglob("*.bounds.json"))), 27)
            self.assertEqual({path: path.read_bytes() for path in maps_before}, maps_before)
            self.assertEqual(requests, [brazilgeo.SOURCE_URL])

    def test_failed_download_does_not_publish_maps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "maps"
            transport = httpx.MockTransport(lambda request: httpx.Response(503))
            client = httpx.Client(transport=transport)
            with (
                patch.object(brazilgeo, "OUTPUT_DIR", output_dir),
                patch.object(brazilgeo.httpx, "Client", return_value=client),
                patch("apps.turi.src.infra.downloader.downloader.BASE_DIR", root),
            ):
                with self.assertRaisesRegex(RuntimeError, "Falha ao baixar"):
                    brazilgeo.generate()

            self.assertEqual(list(output_dir.rglob("*.geojson")), [])

    def test_invalid_tolerance_does_not_clean_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing = root / "BR.geojson"
            existing.write_text("preserve")

            with patch.object(brazilgeo, "OUTPUT_DIR", root):
                for tolerance in (-1, float("nan"), float("inf")):
                    with self.subTest(tolerance=tolerance):
                        with self.assertRaises(ValueError):
                            brazilgeo.generate(tolerance)

            self.assertEqual(existing.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
