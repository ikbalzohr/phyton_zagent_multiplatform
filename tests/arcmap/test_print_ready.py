"""Print-ready template engine: deterministic paths, layout QA, worker contract."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'agents/arcmap/engine'
sys.path.insert(0, str(ENGINE))
from stage2 import print_ready

WORKER = ENGINE / 'orchestrator/adapters/file_worker/arcgis_process.py'
spec = importlib.util.spec_from_file_location('print_worker_client', WORKER)
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)


def element(name, kind, text='', font=8.0, x=1, y=1, w=2, h=1, overflow=False, items=()):
    obj = NS(name=name, type=kind, text=text, fontSize=font,
             elementPositionX=x, elementPositionY=y,
             elementWidth=w, elementHeight=h, isOverflowing=overflow)
    obj.listLegendItemLayers = lambda: [NS(name=v) for v in items]
    return obj


class LayoutFixture:
    def __init__(self):
        self.main = NS(name='Layers', scale=70000,
                       spatialReference=NS(name='WGS_1984_UTM_Zone_51N'))
        self.frames = [self.main, NS(name='New Data Frame',scale=3500000),
                       NS(name='New Data Frame 2',scale=23000000)]
        self.layers = [NS(name='PT BUOL AGRI LESTARI',isGroupLayer=False,visible=True)]
        self.elements = [
            element('Layers', 'DATAFRAME_ELEMENT'),
            element('New Data Frame', 'DATAFRAME_ELEMENT'),
            element('New Data Frame 2', 'DATAFRAME_ELEMENT'),
            element('Legend','LEGEND_ELEMENT',items=['PT BUOL AGRI LESTARI']),
            element('North Arrow','MAPSURROUND_ELEMENT'),
            element('Double Alternating Scale Bar','MAPSURROUND_ELEMENT'),
            element('Title','TEXT_ELEMENT',text='PETA ADMINISTRASI PT BUOL AGRI LESTARI'),
            element('Source','TEXT_ELEMENT',text='SUMBER DATA'),
            element('CRS','TEXT_ELEMENT',text='WGS 1984 UTM Zone 51N'),
        ]
        self.mxd=NS(pageSize=NS(width=29.6968927,height=20.9973753))
    def fake_arcpy(self):
        return NS(mapping=NS(
            ListDataFrames=lambda m:self.frames,
            ListLayoutElements=lambda m:self.elements,
            ListLayers=lambda m, wildcard, df:self.layers,
            ListBrokenDataSources=lambda m:[]))
    def evaluate(self):
        with patch.object(print_ready.engine,'_arcpy',return_value=self.fake_arcpy()):
            return print_ready._layout_qa(self.mxd,'Layers',70000,'WGS_1984_UTM_Zone_51N')


class PrintReadyTests(unittest.TestCase):
    def test_local_source_resolution_and_no_fuzzy_match(self):
        with tempfile.TemporaryDirectory() as root:
            shp=Path(root,'SHP')
            basemap=Path(root,'Basemap')
            shp.mkdir()
            basemap.mkdir()
            (shp/'DESA_PL.shp').write_bytes(b'fixture')
            (basemap/'INSET_BUOL_GE_Z12.ecw').write_bytes(b'fixture')
            a=print_ready._local_dataset(root, r'D:\original\SHP\DESA_PL.shp')
            # Cross-platform source basename must be interpreted by host OS.
            if sys.platform == 'win32':
                self.assertEqual(Path(a[0]),shp/'DESA_PL.shp')
                self.assertEqual(a[1],'SHAPEFILE_WORKSPACE')
                self.assertEqual(a[2],'DESA_PL')
                raster=print_ready._local_dataset(root,r'D:\original\INSET_BUOL_GE_Z12.ecw')
                self.assertEqual(Path(raster[0]),basemap/'INSET_BUOL_GE_Z12.ecw')
            self.assertIsNone(print_ready._local_dataset(root, 'missing.shp'))
            self.assertIsNone(print_ready._local_dataset(root, 'wrong.gdb'))

    def test_root_prefix_is_not_path_containment(self):
        with tempfile.TemporaryDirectory() as parent:
            root=Path(parent,'data')
            twin=Path(parent,'database','SHP','DESA_PL.shp')
            self.assertFalse(print_ready._within(str(twin),str(root)))
            self.assertTrue(print_ready._within(str(root/'SHP'/'DESA_PL.shp'),str(root)))

    def test_page_is_strict_landscape(self):
        item=NS(pageSize=NS(width=29.6968927,height=20.9973753))
        report=print_ready._page_mm(item)
        self.assertAlmostEqual(report['width_mm'],296.969,places=2)
        self.assertEqual(report['orientation'],'landscape')
        item.pageSize.width,item.pageSize.height=21.0,29.7
        with self.assertRaisesRegex(ValueError,'NOT_A4_LANDSCAPE'):
            print_ready._page_mm(item)

    def test_valid_layout_has_required_cartography(self):
        qa=LayoutFixture().evaluate()
        self.assertEqual(qa['scale'],70000)
        self.assertEqual(len(qa['frames']),3)
        self.assertEqual(qa['legend_items'],['PT BUOL AGRI LESTARI'])
        self.assertEqual(qa['grid'],'NOT_INDEPENDENTLY_VERIFIED')

    def test_legend_overflow_is_failure(self):
        f=LayoutFixture()
        f.elements[3].isOverflowing=True
        with self.assertRaisesRegex(ValueError,'LEGEND_OVERFLOW'):
            f.evaluate()

    def test_hidden_inset_frame_is_failure(self):
        f=LayoutFixture()
        f.elements.pop(2)
        with self.assertRaisesRegex(ValueError,'INSET_DATAFRAME_ELEMENT_MISSING'):
            f.evaluate()

    def test_outside_page_is_failure(self):
        f=LayoutFixture()
        f.elements[6].elementPositionX=29.0
        with self.assertRaisesRegex(ValueError,'ELEMENTS_OUTSIDE_PAGE'):
            f.evaluate()

    def test_unreadable_small_font_is_failure(self):
        f=LayoutFixture()
        f.elements[6].fontSize=4.0
        with self.assertRaisesRegex(ValueError,'FONT_TOO_SMALL'):
            f.evaluate()

    def test_missing_source_attribution_is_failure(self):
        f=LayoutFixture()
        f.elements[7].text='NO ATTRIBUTION'
        with self.assertRaisesRegex(ValueError,'REQUIRED_TEXT_MISSING'):
            f.evaluate()

    def test_legend_must_be_subset_of_visible_layers(self):
        f=LayoutFixture()
        f.elements[3].listLegendItemLayers=lambda:[NS(name='MISSING')]
        with self.assertRaisesRegex(ValueError,'LEGEND_OUT_OF_SYNC'):
            f.evaluate()

    def test_rejects_current_before_arcpy(self):
        with self.assertRaises(ValueError):
            print_ready.build('CURRENT', 'data', 'out')

    def test_client_routes_to_file_worker_without_attached(self):
        client=client_module.ArcGISProcessFileWorker(ENGINE,python_exe=sys.executable)
        calls=[]
        client._call=lambda op,arguments,timeout=None: calls.append((op,arguments,timeout)) or {'ok':True,'exports':{'PDF':{'path':'C:/out/a.pdf'},'PNG':{'path':'C:/out/a.png'}}}
        with patch('orchestrator.validators.pdf_export.validate_pdf_png',
                   return_value={'ok':True,'structural_qa_pass':True}) as verifier:
            response=client.print_ready_template(template_mxd='C:/in.mxd',data_root='C:/data',output_root='C:/out')
        self.assertTrue(response['ok'])
        self.assertTrue(response['structural_qa']['structural_qa_pass'])
        self.assertFalse(response['print_ready_accepted'])
        verifier.assert_called_once_with('C:/out/a.pdf','C:/out/a.png',400)
        self.assertEqual(calls[0][0],'print_ready_template')
        self.assertEqual(calls[0][1]['template_mxd'],'C:/in.mxd')
        self.assertEqual(calls[0][2],300)
        self.assertNotIn('CURRENT',calls[0][1].values())


class ExportStructureTests(unittest.TestCase):
    def make_fixture(self, folder, width=841.49, height=595.50,
                     pixel_width=4675, pixel_height=3308):
        import struct
        pdf = Path(folder, 'export.pdf')
        png = Path(folder, 'export.png')
        pdf.write_bytes(
            b'%PDF-1.6\n' +
            b'0' * 4096 +
            ('/Type /Page /MediaBox [0 0 %.2f %.2f]\n' % (width,height)).encode('ascii') +
            b'%%EOF\n')
        png.write_bytes(
            b'\x89PNG\r\n\x1a\n' +
            struct.pack('>I', 13) + b'IHDR' +
            struct.pack('>II', pixel_width, pixel_height) +
            b'\x08\x06\x00\x00\x00' + b'\x00\x00\x00\x00' +
            b'\x00' * 4096)
        return str(pdf), str(png)

    def test_pdf_and_png_dimensions_match_landscape_400_dpi(self):
        from orchestrator.validators.pdf_export import validate_pdf_png
        with tempfile.TemporaryDirectory() as td:
            pdf, png = self.make_fixture(td)
            result = validate_pdf_png(pdf,png,400)
            self.assertTrue(result['structural_qa_pass'],result)
            self.assertFalse(result['print_ready_accepted'])
            self.assertEqual(result['metrics']['pdf_page_count'],1)

    def test_wrong_page_shape_is_rejected(self):
        from orchestrator.validators.pdf_export import validate_pdf_png
        with tempfile.TemporaryDirectory() as td:
            pdf,png = self.make_fixture(td, width=595.5,height=841.5)
            result = validate_pdf_png(pdf,png,400)
            self.assertFalse(result['ok'])
            self.assertIn('PDF_PAGE_NOT_A4_LANDSCAPE',result['errors'])

    def test_dpi_dimensions_mismatch_is_rejected(self):
        from orchestrator.validators.pdf_export import validate_pdf_png
        with tempfile.TemporaryDirectory() as td:
            pdf,png = self.make_fixture(td,pixel_width=1280,pixel_height=720)
            result = validate_pdf_png(pdf,png,400)
            self.assertFalse(result['ok'])
            self.assertIn('PNG_DPI_OR_PAGE_MISMATCH',result['errors'])

    def test_missing_or_broken_files_fail_closed(self):
        from orchestrator.validators.pdf_export import validate_pdf_png
        with tempfile.TemporaryDirectory() as td:
            pdf,png = self.make_fixture(td)
            Path(pdf).write_bytes(b'bad')
            result = validate_pdf_png(pdf,png,400)
            self.assertFalse(result['ok'])
            self.assertIn('PDF_HEADER_INVALID',result['errors'])
            Path(png).unlink()
            result = validate_pdf_png(pdf,png,400)
            self.assertFalse(result['ok'])
            self.assertIn('EXPORT_FILE_MISSING',result['errors'])


if __name__=='__main__':
    unittest.main()
