""" Test for the Component class"""

import unittest
from six import text_type

import numpy as np

from openmdao.core.component import Component

class TestComponent(unittest.TestCase):

    def setUp(self):
        self.comp = Component()

    def test_promotes(self):
        self.comp.add_param("xxyyzz", 0.0)
        self.comp.add_param("foobar", 0.0)
        self.comp.add_output("a:bcd:efg", -1)
        self.comp.add_output("x_y_z", np.zeros(10))

        self.comp._promotes = ('*',)
        for name in self.comp._params_dict:
            self.assertTrue(self.comp.promoted(name))
        for name in self.comp._unknowns_dict:
            self.assertTrue(self.comp.promoted(name))

        self.assertFalse(self.comp.promoted('blah'))

        self.comp._promotes = ('x*',)
        for name in self.comp._params_dict:
            if name.startswith('x'):
                self.assertTrue(self.comp.promoted(name))
            else:
                self.assertFalse(self.comp.promoted(name))
        for name in self.comp._unknowns_dict:
            if name.startswith('x'):
                self.assertTrue(self.comp.promoted(name))
            else:
                self.assertFalse(self.comp.promoted(name))

        self.comp._promotes = ('*:efg',)
        for name in self.comp._params_dict:
            if name.endswith(':efg'):
                self.assertTrue(self.comp.promoted(name))
            else:
                self.assertFalse(self.comp.promoted(name))
        for name in self.comp._unknowns_dict:
            if name.endswith(':efg'):
                self.assertTrue(self.comp.promoted(name))
            else:
                self.assertFalse(self.comp.promoted(name))
        # catch bad type on _promotes
        try:
            self.comp._promotes = ('*')
            self.comp.promoted('xxyyzz')
        except Exception as err:
            self.assertEqual(text_type(err),
                             "'' promotes must be specified as a list, tuple or other iterator of strings, but '*' was specified")

    def test_add_params(self):
        self.comp.add_param("x", 0.0)
        self.comp.add_param("y", 0.0)
        self.comp.add_param("z", shape=(1,))
        self.comp.add_param("t", shape=2)
        self.comp.add_param("u", shape=1)

        with self.assertRaises(ValueError) as cm:
            self.comp.add_param("w")

        self.assertEquals(str(cm.exception), "Shape of param 'w' must be specified because 'val' is not set")

        params, unknowns = self.comp._setup_variables()

        self.assertEquals(["x", "y", "z", "t", "u"], list(params.keys()))

        self.assertEquals(params["x"], {'shape': 1, 'promoted_name': 'x', 'pathname': 'x', 'val': 0.0, 'size': 1})
        self.assertEquals(params["y"], {'shape': 1, 'promoted_name': 'y', 'pathname': 'y', 'val': 0.0, 'size': 1})
        np.testing.assert_array_equal(params["z"]["val"], np.zeros((1,)))
        np.testing.assert_array_equal(params["t"]["val"], np.zeros((2,)))
        self.assertEquals(params["u"], {'shape': 1, 'promoted_name': 'u', 'pathname': 'u', 'val': 0.0, 'size': 1})

    def test_add_outputs(self):
        self.comp.add_output("x", -1)
        self.comp.add_output("y", np.zeros(10))
        self.comp.add_output("z", shape=(10,))
        self.comp.add_output("t", shape=2)
        self.comp.add_output("u", shape=1)

        with self.assertRaises(ValueError) as cm:
            self.comp.add_output("w")

        self.assertEquals(str(cm.exception), "Shape of output 'w' must be specified because 'val' is not set")

        params, unknowns = self.comp._setup_variables()

        self.assertEquals(["x", "y", "z", "t", "u"], list(unknowns.keys()))

        self.assertIsInstance(unknowns["x"]["val"], int)
        self.assertIsInstance(unknowns["y"]["val"], np.ndarray)
        self.assertIsInstance(unknowns["z"]["val"], np.ndarray)
        self.assertIsInstance(unknowns["t"]["val"], np.ndarray)
        self.assertIsInstance(unknowns["u"]["val"], float)

        self.assertEquals(unknowns["x"], {'pass_by_obj': True, 'promoted_name': 'x', 'pathname': 'x', 'val': -1, 'size': 0})
        self.assertEquals(list(unknowns["y"]["val"]), 10*[0])
        np.testing.assert_array_equal(unknowns["z"]["val"], np.zeros((10,)))
        np.testing.assert_array_equal(unknowns["t"]["val"], np.zeros((2,)))
        self.assertEquals(unknowns["u"], {'shape': 1, 'promoted_name': 'u', 'pathname': 'u', 'val': 0.0, 'size': 1})

    def test_add_states(self):
        self.comp.add_state("s1", 0.0)
        self.comp.add_state("s2", 6.0)
        self.comp.add_state("s3", shape=(1, ))
        self.comp.add_state("s4", shape=2)
        self.comp.add_state("s5", shape=1)

        with self.assertRaises(ValueError) as cm:
            self.comp.add_state("s6")

        self.assertEquals(str(cm.exception), "Shape of state 's6' must be specified because 'val' is not set")
        params, unknowns = self.comp._setup_variables()

        self.assertEquals(["s1", "s2", "s3", "s4", "s5"], list(unknowns.keys()))

        self.assertEquals(unknowns["s1"], {'val': 0.0, 'state': True, 'shape': 1, 'pathname': 's1', 'promoted_name': 's1', 'size': 1})
        self.assertEquals(unknowns["s2"], {'val': 6.0, 'state': True, 'shape': 1, 'pathname': 's2', 'promoted_name': 's2', 'size': 1})
        np.testing.assert_array_equal(unknowns["s3"]["val"], np.zeros((1,)))
        np.testing.assert_array_equal(unknowns["s4"]["val"], np.zeros((2,)))
        self.assertEquals(unknowns["s5"], {'val': 0.0, 'state': True, 'shape': 1, 'pathname': 's5', 'promoted_name': 's5', 'size': 1})

    def test_variable_access(self):
        self.comp.add_output("x_y_z", np.zeros(10))

        try:
            self.comp["x_y_z"]
        except Exception as err:
            self.assertEqual(str(err),
                             "Variable 'x_y_z' must be accessed from a containing Group")
        else:
            self.fail("Exception expected")

    def test_generate_numpydocstring(self):
        self.comp.add_param("xxyyzz", 0.0)
        self.comp.add_param("t", shape=2)
        self.comp.add_output("x", -1)
        self.comp.add_state("s1", 0.0)

        test_string = self.comp.generate_docstring()
        self.assertEqual(test_string, '\t"""\n\n\tAttributes\n\t----------\n\n\t\txxyyzz : param \n\n\t\t\t<Insert description here.>\n\n\t\tt : param \n\n\t\t\t<Insert description here.>\n\n\t\tx :  unknown \n\n\t\t\t<Insert description here.>\n\n\t\ts1 :  unknown \n\n\t\t\t<Insert description here.>\n\n\n\tNote\n\t----\n\n\n\t"""\n')

if __name__ == "__main__":
    unittest.main()
