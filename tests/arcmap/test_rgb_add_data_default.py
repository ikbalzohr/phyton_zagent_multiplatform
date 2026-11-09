# -*- coding: utf-8 -*-
"""Regression: preserve ArcMap Add Data native RGB renderer; never update it."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..',
                                    'agents', 'arcmap', 'engine'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from stage2.rgb_composite import request_rgb_composite


class Layer(object):
    def __init__(self, name='base.ecw', bands=3, visible=True,
                 broken=False, group=False, raster=True):
        self.name = name
        self.visible = visible
        self.isBroken = broken
        self.isGroupLayer = group
        self.isRasterLayer = raster
        self.dataSource = '/test/' + name
        self._bands = bands


class Frame(object):
    name = 'Layers'


class Raster(object):
    def __init__(self, bands):
        self.bandCount = bands


class Mapping(object):
    def __init__(self, layers):
        self.layers = layers
        self.frame = Frame()

    def ListDataFrames(self, mxd):
        return [self.frame]

    def ListLayers(self, mxd, name, frame):
        return self.layers

    def UpdateLayer(self, *args):
        raise AssertionError('UpdateLayer must never be called')

    def AddLayer(self, *args):
        raise AssertionError('AddLayer must never be called')

    def Layer(self, *args):
        raise AssertionError('Layer must never be recreated')


class FakeArcPy(object):
    def __init__(self, layers):
        self.mapping = Mapping(layers)
        self.layers = layers

    def Raster(self, path):
        for layer in self.layers:
            if layer.dataSource == path:
                return Raster(layer._bands)
        raise AssertionError('Unknown path ' + path)

    def MakeRasterLayer_management(self, *args):
        raise AssertionError('MakeRasterLayer must never be called')


class RGBTests(unittest.TestCase):
    def test_three_band_native_add_data_unchanged(self):
        layer = Layer()
        tool = FakeArcPy([layer])
        result = request_rgb_composite(object(), tool)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['band_count'], 3)
        self.assertEqual(result[0]['strategy'],
                         'PRESERVE_ARCMAP_ADD_DATA_DEFAULT')
        self.assertIs(tool.mapping.layers[0], layer)

    def test_single_band_rejected(self):
        tool = FakeArcPy([Layer(bands=1)])
        with self.assertRaises(ValueError) as exc:
            request_rgb_composite(object(), tool)
        self.assertIn('RGB_NEEDS_VALIDATED_BAND_MAPPING', str(exc.exception))

    def test_broken_raster_rejected(self):
        tool = FakeArcPy([Layer(broken=True)])
        with self.assertRaises(ValueError):
            request_rgb_composite(object(), tool)

    def test_invisible_raster_ignored(self):
        tool = FakeArcPy([Layer(visible=False)])
        self.assertEqual(request_rgb_composite(object(), tool), [])

    def test_vector_and_groups_ignored(self):
        tool = FakeArcPy([Layer(raster=False), Layer(group=True)])
        self.assertEqual(request_rgb_composite(object(), tool), [])


if __name__ == '__main__':
    unittest.main()
